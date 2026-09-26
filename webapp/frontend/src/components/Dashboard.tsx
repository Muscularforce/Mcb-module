import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchEntries } from '../api';
import type { Entry, EntryType, RealtimeChange } from '../types';
import {
  entryReadKey,
  firstVisitReadKeys,
  hasReadMarker,
  mapSupabaseRow,
  reconcileRealtimeChanges,
} from '../lib/entries.ts';
import { EntryCard } from './EntryCard';
import { EntryModal } from './EntryModal';
import {
  AlertCircle,
  Bell,
  Book,
  ChevronDown,
  Clock3,
  FileText,
  Inbox,
  RefreshCw,
  Search,
  Sparkles,
  Wifi,
  WifiOff,
} from 'lucide-react';
import jsRdLogo from '../assets/js_rd_logo.png';
import { supabase } from '../lib/supabase';

type FilterType = 'all' | EntryType;
type RealtimeState = 'connecting' | 'connected' | 'error';

const PAGE_SIZE = 6;
const STALE_AFTER_MS = 5 * 60 * 1000;
const CACHE_KEY = 'mcb_cached_entries';
const CACHE_TIME_KEY = 'mcb_cached_at';
const READ_IDS_KEY = 'mcb_read_entry_ids';
const REALTIME_FALLBACK_MS = 2000;
const REALTIME_RETRY_MAX_MS = 30000;

interface CacheState {
  entries: Entry[];
  syncedAt: string | null;
  valid: boolean;
}

interface CachedPayload {
  version: number;
  entries: unknown[];
  syncedAt: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
);

const getErrorMessage = (error: unknown): string => {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error) return error;
  return 'The latest data could not be loaded.';
};

const isValidTimestamp = (value: unknown): value is string => (
  typeof value === 'string' && Number.isFinite(Date.parse(value))
);

const mapCachedRows = (value: unknown): Entry[] => {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map(row => mapSupabaseRow(row));
};

const readCacheState = (): CacheState => {
  if (typeof window === 'undefined') return { entries: [], syncedAt: null, valid: false };
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return { entries: [], syncedAt: null, valid: false };
    const parsed: unknown = JSON.parse(raw);
    if (isRecord(parsed) && Array.isArray(parsed.entries)) {
      const syncedAt = isValidTimestamp(parsed.syncedAt)
        ? parsed.syncedAt
        : window.localStorage.getItem(CACHE_TIME_KEY);
      if (!isValidTimestamp(syncedAt)) return { entries: [], syncedAt: null, valid: false };
      return {
        entries: mapCachedRows(parsed.entries),
        syncedAt,
        valid: true,
      };
    }
    if (Array.isArray(parsed)) {
      const syncedAt = window.localStorage.getItem(CACHE_TIME_KEY);
      if (!isValidTimestamp(syncedAt)) return { entries: [], syncedAt: null, valid: false };
      return { entries: mapCachedRows(parsed), syncedAt, valid: true };
    }
  } catch {
    return { entries: [], syncedAt: null, valid: false };
  }
  return { entries: [], syncedAt: null, valid: false };
};

const writeCachedEntries = (entries: Entry[], syncedAt: string): void => {
  if (typeof window === 'undefined') return;
  try {
    const payload: CachedPayload = {
      version: 1,
      entries,
      syncedAt,
    };
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
    window.localStorage.setItem(CACHE_TIME_KEY, syncedAt);
  } catch {
    return;
  }
};

const readReadKeys = (): Set<string> | null => {
  if (typeof window === 'undefined') return null;
  try {
    const value = window.localStorage.getItem(READ_IDS_KEY);
    if (!value) return null;
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) return new Set<string>();
    return new Set(parsed
      .filter(id => typeof id === 'string' || typeof id === 'number')
      .map(id => String(id)));
  } catch {
    return new Set<string>();
  }
};

const writeReadKeys = (keys: ReadonlySet<string>): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(READ_IDS_KEY, JSON.stringify(Array.from(keys)));
  } catch {
    return;
  }
};

const formatDateTime = (value: string): string => {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Date(timestamp).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
};

const formatRelativeTime = (value: string, now: number): string => {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return 'an unknown time';
  const difference = Math.max(0, now - timestamp);
  const minutes = Math.floor(difference / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
};

function useAnimatedCounter(target: number, duration = 1200) {
  const [count, setCount] = useState(0);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    if (target === 0) {
      setCount(0);
      return undefined;
    }
    const start = performance.now();
    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.round(eased * target));
      if (progress < 1) frameRef.current = requestAnimationFrame(animate);
    };
    frameRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frameRef.current);
  }, [target, duration]);

  return count;
}

const Particles: React.FC = () => {
  const particles = useMemo(() => Array.from({ length: 40 }, (_, index) => ({
    id: index,
    x: Math.random() * 100,
    y: Math.random() * 100,
    size: Math.random() * 2.5 + 0.8,
    duration: Math.random() * 25 + 18,
    delay: Math.random() * -30,
    opacity: Math.random() * 0.4 + 0.1,
  })), []);

  return (
    <div className="particles-container" aria-hidden="true">
      {particles.map(particle => (
        <div
          key={particle.id}
          className="particle"
          style={{
            left: `${particle.x}%`,
            top: `${particle.y}%`,
            width: `${particle.size}px`,
            height: `${particle.size}px`,
            opacity: particle.opacity,
            animationDuration: `${particle.duration}s`,
            animationDelay: `${particle.delay}s`,
          }}
        />
      ))}
    </div>
  );
};

export const Dashboard: React.FC = () => {
  const [initialCache] = useState<CacheState>(() => readCacheState());
  const [entries, setEntries] = useState<Entry[]>(initialCache.entries);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<string | null>(initialCache.syncedAt);
  const [now, setNow] = useState(() => Date.now());
  const [realtimeState, setRealtimeState] = useState<RealtimeState>('connecting');
  const [realtimeRetry, setRealtimeRetry] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<FilterType>('all');
  const [selectedEntry, setSelectedEntry] = useState<Entry | null>(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [readKeys, setReadKeys] = useState<Set<string>>(() => {
    const stored = readReadKeys();
    if (stored) return stored;
    if (initialCache.entries.length === 0) return new Set<string>();
    const baseline = firstVisitReadKeys(initialCache.entries);
    writeReadKeys(baseline);
    return baseline;
  });
  const spotlightRef = useRef<HTMLDivElement>(null);
  const entriesRef = useRef<Entry[]>(entries);
  const readKeysRef = useRef<Set<string>>(readKeys);
  const lastSuccessfulAtRef = useRef<string | null>(initialCache.syncedAt);
  const cacheValidRef = useRef(initialCache.valid);
  const isFetchingRef = useRef(false);
  const requestIdRef = useRef(0);
  const eventLogRef = useRef<RealtimeChange[]>([]);
  const authoritativeCursorRef = useRef(0);
  const appliedCursorRef = useRef(0);
  const loadEntriesRef = useRef<(() => Promise<void>) | null>(null);
  const refetchTimerRef = useRef<number | null>(null);

  const handleMouseMove = useCallback((event: React.MouseEvent) => {
    if (!spotlightRef.current) return;
    spotlightRef.current.style.setProperty('--mx', `${event.clientX}px`);
    spotlightRef.current.style.setProperty('--my', `${event.clientY}px`);
  }, []);

  const commitReadKeys = useCallback((next: Set<string>) => {
    readKeysRef.current = next;
    setReadKeys(next);
    writeReadKeys(next);
  }, []);

  const scheduleAuthoritativeRefetch = useCallback(() => {
    if (typeof window === 'undefined') return;
    if (refetchTimerRef.current !== null) return;
    refetchTimerRef.current = window.setTimeout(() => {
      refetchTimerRef.current = null;
      void loadEntriesRef.current?.();
    }, 500);
  }, []);

  const persistEntries = useCallback((
    nextEntries: Entry[],
    syncedAt: string | null,
    successful: boolean,
  ) => {
    entriesRef.current = nextEntries;
    setEntries(nextEntries);
    if (successful && syncedAt) {
      lastSuccessfulAtRef.current = syncedAt;
      setLastSuccessfulAt(syncedAt);
      cacheValidRef.current = true;
      writeCachedEntries(nextEntries, syncedAt);
      return;
    }
    if (cacheValidRef.current && lastSuccessfulAtRef.current) {
      writeCachedEntries(nextEntries, lastSuccessfulAtRef.current);
    }
  }, []);

  const ensureReadState = useCallback((dataset: Entry[]) => {
    const stored = readReadKeys();
    if (stored) {
      if (stored.size > 0 || readKeysRef.current.size > 0) commitReadKeys(stored);
      return;
    }
    if (dataset.length === 0) return;
    commitReadKeys(firstVisitReadKeys(dataset));
  }, [commitReadKeys]);

  const loadEntries = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    setLoadError(null);

    try {
      const data = await fetchEntries();
      const pendingEvents = eventLogRef.current.slice(authoritativeCursorRef.current);
      const reconciled = reconcileRealtimeChanges(data, pendingEvents);
      if (requestId !== requestIdRef.current) return;
      const successfulAt = new Date().toISOString();
      persistEntries(reconciled.entries, successfulAt, true);
      authoritativeCursorRef.current = eventLogRef.current.length;
      appliedCursorRef.current = eventLogRef.current.length;
      eventLogRef.current = [];
      ensureReadState(reconciled.entries);
      setNow(Date.now());
      if (reconciled.needsAuthoritativeRefetch) scheduleAuthoritativeRefetch();
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      const pendingEvents = eventLogRef.current.slice(appliedCursorRef.current);
      if (pendingEvents.length > 0) {
        const reconciled = reconcileRealtimeChanges(entriesRef.current, pendingEvents);
        appliedCursorRef.current = eventLogRef.current.length;
        if (!reconciled.needsAuthoritativeRefetch) {
          persistEntries(reconciled.entries, new Date().toISOString(), true);
          setLoadError(null);
        } else {
          persistEntries(reconciled.entries, null, false);
          scheduleAuthoritativeRefetch();
        }
      }
      setLoadError(getErrorMessage(error));
    } finally {
      if (requestId === requestIdRef.current) {
        isFetchingRef.current = false;
        setLoading(false);
      }
    }
  }, [ensureReadState, persistEntries, scheduleAuthoritativeRefetch]);

  loadEntriesRef.current = loadEntries;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  const handleRealtimeChange = useCallback((change: RealtimeChange) => {
    eventLogRef.current.push(change);
    if (isFetchingRef.current) return;

    const pendingEvents = eventLogRef.current.slice(appliedCursorRef.current);
    const reconciled = reconcileRealtimeChanges(entriesRef.current, pendingEvents);
    appliedCursorRef.current = eventLogRef.current.length;
    const syncedAt = new Date().toISOString();
    if (!reconciled.needsAuthoritativeRefetch) {
      persistEntries(reconciled.entries, syncedAt, true);
      setLoadError(null);
    } else {
      persistEntries(reconciled.entries, null, false);
      scheduleAuthoritativeRefetch();
    }
    writeReadKeys(readKeysRef.current);
  }, [persistEntries, scheduleAuthoritativeRefetch]);

  useEffect(() => {
    let disposed = false;
    let channel: ReturnType<typeof supabase.channel> | null = null;
    let retryTimer: number | null = null;
    let fallbackTimer: number | null = null;
    let retryAttempt = 0;
    let initialLoadStarted = false;

    const removeCurrentChannel = () => {
      const current = channel;
      channel = null;
      if (current) void supabase.removeChannel(current);
    };

    const scheduleReconnect = () => {
      if (disposed || retryTimer !== null) return;
      const delay = Math.min(1000 * 2 ** retryAttempt, REALTIME_RETRY_MAX_MS);
      retryAttempt += 1;
      retryTimer = window.setTimeout(() => {
        retryTimer = null;
        removeCurrentChannel();
        connect();
      }, delay);
    };

    const connect = () => {
      if (disposed) return;
      setRealtimeState('connecting');
      const nextChannel = supabase.channel('entries_realtime_sync');
      channel = nextChannel;
      nextChannel
        .on(
          'postgres_changes',
          { event: '*', schema: 'public', table: 'entries' },
          payload => handleRealtimeChange(payload as unknown as RealtimeChange),
        )
        .subscribe(status => {
          if (disposed) return;
          if (status === 'SUBSCRIBED') {
            retryAttempt = 0;
            setRealtimeState('connected');
            if (!initialLoadStarted) {
              initialLoadStarted = true;
              void loadEntries();
            } else {
              void loadEntries();
            }
          } else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
            setRealtimeState('error');
            scheduleReconnect();
          } else {
            setRealtimeState('connecting');
          }
        });
    };

    connect();
    fallbackTimer = window.setTimeout(() => {
      if (!initialLoadStarted) {
        initialLoadStarted = true;
        void loadEntries();
      }
    }, REALTIME_FALLBACK_MS);

    return () => {
      disposed = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      if (fallbackTimer !== null) window.clearTimeout(fallbackTimer);
      removeCurrentChannel();
      if (refetchTimerRef.current !== null) {
        window.clearTimeout(refetchTimerRef.current);
        refetchTimerRef.current = null;
      }
    };
  }, [handleRealtimeChange, loadEntries, realtimeRetry]);

  useEffect(() => {
    setSelectedEntry(current => {
      if (!current) return null;
      return entries.find(entry => (
        entry.entry_type === current.entry_type && String(entry.id) === String(current.id)
      )) ?? null;
    });
  }, [entries]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [activeFilter, searchQuery]);

  const handleEntryClick = useCallback((entry: Entry) => {
    setSelectedEntry(entry);
    if (hasReadMarker(readKeysRef.current, entry)) return;
    const next = new Set(readKeysRef.current);
    next.add(entryReadKey(entry));
    commitReadKeys(next);
  }, [commitReadKeys]);

  const getUnreadCount = useCallback((type: EntryType) => (
    entries.filter(entry => entry.type === type && !hasReadMarker(readKeys, entry)).length
  ), [entries, readKeys]);

  const filteredEntries = useMemo(() => {
    let result = entries;
    if (activeFilter !== 'all') result = result.filter(entry => entry.type === activeFilter);
    const query = searchQuery.trim().toLowerCase();
    if (query) {
      result = result.filter(entry => (
        entry.title.toLowerCase().includes(query)
        || entry.content.toLowerCase().includes(query)
        || entry.label.toLowerCase().includes(query)
        || (entry.teacher?.toLowerCase().includes(query) ?? false)
      ));
    }
    return result;
  }, [entries, activeFilter, searchQuery]);

  const visibleEntries = filteredEntries.slice(0, visibleCount);
  const hasMore = visibleCount < filteredEntries.length;
  const latestEntryUpdatedAt = useMemo(() => {
    let latestTimestamp = Number.NEGATIVE_INFINITY;
    let latestValue: string | null = null;
    for (const entry of entries) {
      if (!entry.updated_at) continue;
      const timestamp = Date.parse(entry.updated_at);
      if (Number.isFinite(timestamp) && timestamp > latestTimestamp) {
        latestTimestamp = timestamp;
        latestValue = entry.updated_at;
      }
    }
    return latestValue;
  }, [entries]);
  const syncTimestamp = lastSuccessfulAt ? Date.parse(lastSuccessfulAt) : Number.NaN;
  const isStale = Boolean(loadError)
    || !Number.isFinite(syncTimestamp)
    || now - syncTimestamp >= STALE_AFTER_MS;
  const hasUsableEntries = entries.length > 0;
  const showInitialLoading = loading && !hasUsableEntries && !cacheValidRef.current && !loadError;
  const showInitialError = Boolean(loadError) && !hasUsableEntries && !cacheValidRef.current;
  const statusClass = loadError ? 'error' : isStale || realtimeState === 'error' ? 'stale' : 'fresh';
  const statusTitle = loadError
    ? 'Refresh failed'
    : realtimeState === 'error'
      ? 'Realtime unavailable'
      : isStale
        ? 'Data may be stale'
        : 'Data available';
  const syncDetail = lastSuccessfulAt
    ? `Last successful sync ${formatRelativeTime(lastSuccessfulAt, now)} (${formatDateTime(lastSuccessfulAt)})`
    : 'Waiting for the first successful sync.';
  const entryUpdateDetail = latestEntryUpdatedAt
    ? ` Newest entry update ${formatRelativeTime(latestEntryUpdatedAt, now)} (${formatDateTime(latestEntryUpdatedAt)}).`
    : '';
  const statusDetail = loadError
    ? `Showing the last available entries. ${syncDetail}. ${getErrorMessage(loadError)}${entryUpdateDetail}`
    : `${syncDetail}.${entryUpdateDetail}`;

  const diaryCount = useAnimatedCounter(entries.filter(entry => entry.type === 'diary').length);
  const worksheetCount = useAnimatedCounter(entries.filter(entry => entry.type === 'worksheet').length);
  const announcementCount = useAnimatedCounter(entries.filter(entry => entry.type === 'announcement').length);

  if (showInitialLoading) {
    return (
      <div className="loading-container">
        <div className="loading-orb">
          <div className="loading-orb-ring" />
          <div className="loading-orb-ring r2" />
          <div className="loading-orb-ring r3" />
          <div className="loading-orb-core" />
        </div>
        <span className="loading-text">Loading your dashboard<span className="loading-dots">...</span></span>
      </div>
    );
  }

  if (showInitialError) {
    return (
      <div className="load-state-container">
        <AlertCircle size={34} />
        <h1>Unable to load entries</h1>
        <p>{loadError}</p>
        <button className="retry-button" type="button" onClick={() => { void loadEntries(); }}>
          <RefreshCw size={16} />
          Retry
        </button>
      </div>
    );
  }

  const filters: { key: FilterType; label: string; icon: React.ReactNode }[] = [
    { key: 'all', label: 'All Entries', icon: <Sparkles size={13} /> },
    { key: 'diary', label: 'Diary', icon: <Book size={13} /> },
    { key: 'worksheet', label: 'Worksheets', icon: <FileText size={13} /> },
    { key: 'announcement', label: 'Announcements', icon: <Bell size={13} /> },
  ];

  return (
    <div className="app-wrapper" ref={spotlightRef} onMouseMove={handleMouseMove}>
      <div className="cursor-spotlight" />
      <Particles />
      <div className="aurora" aria-hidden="true">
        <div className="aurora-band a1" />
        <div className="aurora-band a2" />
        <div className="aurora-band a3" />
      </div>
      <div className="noise-overlay" />

      <div className="app-container">
        <header className="header">
          <div className="header-top-branding">
            <div className="brand-glow" />
            <span className="header-brand-by">MADE BY</span>
            <a href="https://discord.gg/966WM3djK" target="_blank" rel="noopener noreferrer" className="header-brand-link" title="Join J's R&D Discord Server">
              <img src={jsRdLogo} alt="J's R&D" className="header-brand-logo" />
              <span className="header-brand-name">J's R&D</span>
            </a>
          </div>

          <div className="header-hero">
            <div className="hero-glow" />
            <div className="header-logo-wrapper">
              <div className="logo-orb">
                <svg viewBox="0 0 24 24" className="mcb-logo-svg" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="url(#lg1)" />
                  <path d="M2 17L12 22L22 17" stroke="url(#lg2)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M2 12L12 17L22 12" stroke="url(#lg1)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  <defs>
                    <linearGradient id="lg1" x1="2" y1="2" x2="22" y2="17" gradientUnits="userSpaceOnUse">
                      <stop stopColor="#818cf8" />
                      <stop offset="1" stopColor="#a78bfa" />
                    </linearGradient>
                    <linearGradient id="lg2" x1="2" y1="12" x2="22" y2="22" gradientUnits="userSpaceOnUse">
                      <stop stopColor="#f59e0b" />
                      <stop offset="1" stopColor="#ef4444" />
                    </linearGradient>
                  </defs>
                </svg>
              </div>
              <div className="mcb-logo-text">
                <span className="logo-my">my</span>
                <span className="logo-classboard">classboard</span>
              </div>
            </div>
            <p className="header-subtitle">The Better Mcb</p>
            <div style={{ marginTop: '12px', background: 'rgba(239, 68, 68, 0.1)', color: '#ef4444', padding: '6px 16px', borderRadius: '20px', fontSize: '0.85rem', display: 'inline-flex', alignItems: 'center', gap: '6px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
              <Sparkles size={14} />
              Website is under development
            </div>
          </div>
        </header>

        <div className={`data-status ${statusClass}`} role="status" aria-live="polite">
          <div className="data-status-icon">
            {loadError || isStale ? <Clock3 size={16} /> : <Wifi size={16} />}
          </div>
          <div className="data-status-copy">
            <strong>{statusTitle}</strong>
            <span>{statusDetail}{loading && hasUsableEntries ? ' Refreshing in background.' : ''}</span>
          </div>
          <div className="data-status-actions">
            <span className={`realtime-indicator ${realtimeState}`}>
              {realtimeState === 'connected' ? <Wifi size={13} /> : <WifiOff size={13} />}
              {realtimeState === 'connected' ? 'Realtime connected' : realtimeState === 'error' ? 'Realtime unavailable' : 'Connecting'}
            </span>
            {loadError && (
              <button className="retry-button compact" type="button" onClick={() => { void loadEntries(); }}>
                <RefreshCw size={14} />
                Retry
              </button>
            )}
            {realtimeState === 'error' && (
              <button className="retry-button compact" type="button" onClick={() => setRealtimeRetry(value => value + 1)}>
                <RefreshCw size={14} />
                Reconnect
              </button>
            )}
          </div>
        </div>

        <div className="stats-bar">
          <div className="stat-card">
            <div className="stat-icon diary"><Book size={20} /></div>
            <div className="stat-data">
              <div className="stat-number">{diaryCount}</div>
              <div className="stat-label">Diary Entries</div>
            </div>
            <div className="stat-glow diary" />
          </div>
          <div className="stat-card">
            <div className="stat-icon worksheet"><FileText size={20} /></div>
            <div className="stat-data">
              <div className="stat-number">{worksheetCount}</div>
              <div className="stat-label">Worksheets</div>
            </div>
            <div className="stat-glow worksheet" />
          </div>
          <div className="stat-card">
            <div className="stat-icon announcement"><Bell size={20} /></div>
            <div className="stat-data">
              <div className="stat-number">{announcementCount}</div>
              <div className="stat-label">Announcements</div>
            </div>
            <div className="stat-glow announcement" />
          </div>
        </div>

        <div className="search-container">
          <div className="search-glow" />
          <label className="sr-only" htmlFor="search-bar">Search entries</label>
          <input
            id="search-bar"
            type="text"
            className="search-bar"
            placeholder="Search by subject, teacher, or keyword..."
            value={searchQuery}
            onChange={event => setSearchQuery(event.target.value)}
          />
          <Search size={18} className="search-icon" />
        </div>

        <div className="filter-tabs" role="group" aria-label="Entry filters">
          {filters.map(filter => {
            const count = filter.key !== 'all' ? getUnreadCount(filter.key as EntryType) : 0;
            return (
              <button
                key={filter.key}
                type="button"
                className={`filter-tab ${activeFilter === filter.key ? 'active' : ''}`}
                aria-pressed={activeFilter === filter.key}
                onClick={() => setActiveFilter(filter.key)}
              >
                {filter.icon}
                {filter.label}
                {count > 0 && (
                  <span className="tab-badge" aria-label={`${count} unread`}>
                    {count > 9 ? '9+' : count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="entries-grid">
          {filteredEntries.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon-wrapper">
                <Inbox size={40} />
              </div>
              <p>{entries.length === 0 ? 'No entries are available yet.' : 'No entries match your search.'}</p>
            </div>
          ) : (
            visibleEntries.map((entry, index) => (
              <EntryCard
                key={entryReadKey(entry)}
                entry={entry}
                onClick={handleEntryClick}
                index={index}
              />
            ))
          )}
        </div>

        {hasMore && (
          <div className="view-more-container">
            <button
              type="button"
              className="view-more-btn"
              onClick={() => setVisibleCount(previous => previous + PAGE_SIZE)}
            >
              <ChevronDown size={16} className="view-more-chevron" />
              View More
              <span className="view-more-count">
                {filteredEntries.length - visibleCount} remaining
              </span>
            </button>
          </div>
        )}

        <footer className="dashboard-footer">
          <div className="footer-content">
            <div className="footer-left">
              <span className="footer-label">Made by</span>
              <div className="company-info-wrapper">
                <img src={jsRdLogo} alt="J's R&D" className="company-logo-img" />
                <div className="company-text-wrapper">
                  <span className="company-name">J's R&amp;D</span>
                  <span className="company-subtitle">Jovan's Research and Development</span>
                </div>
              </div>
            </div>
            <div className="footer-right">
              <a href="https://discord.gg/966WM3djK" target="_blank" rel="noopener noreferrer" className="discord-btn">
                <span className="discord-btn-glow" />
                <span className="discord-btn-ring r1" />
                <span className="discord-btn-ring r2" />
                <span className="discord-btn-ring r3" />
                <svg viewBox="0 0 127.14 96.36" className="discord-icon-svg" fill="currentColor">
                  <path d="M107.7,8.07A105.15,105.15,0,0,0,77.26,0a77.19,77.19,0,0,0-3.3,6.83A96.67,96.67,0,0,0,53.22,6.83,77.19,77.19,0,0,0,49.88,0,105.15,105.15,0,0,0,19.44,8.07C3.66,31.58-1.86,54.65,1,77.53A105.73,105.73,0,0,0,32,96.36a77.7,77.7,0,0,0,6.63-10.85,68.43,68.43,0,0,1-10.45-5c.87-.64,1.72-1.32,2.53-2a75.46,75.46,0,0,0,72.77,0c.81.7,1.66,1.38,2.53,2a68.61,68.61,0,0,1-10.45,5,78.5,78.5,0,0,0,6.63,10.85,105.73,105.73,0,0,0,31.06-18.83C129.86,48.86,123.63,26,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53S36.18,40.36,42.45,40.36,53.83,46,53.83,53,48.72,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.24,60,73.24,53S78.41,40.36,84.69,40.36,96.07,46,96.07,53,91,65.69,84.69,65.69Z" />
                </svg>
                <span className="discord-btn-text">Join Discord</span>
              </a>
            </div>
          </div>
        </footer>
      </div>

      <EntryModal entry={selectedEntry} onClose={() => setSelectedEntry(null)} />
    </div>
  );
};
