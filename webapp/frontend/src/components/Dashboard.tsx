import React, { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import { fetchEntries } from '../api';
import { Entry, EntryType } from '../types';
import { EntryCard } from './EntryCard';
import { EntryModal } from './EntryModal';
import { Search, Book, FileText, Bell, Inbox, ChevronDown, Sparkles } from 'lucide-react';
import jsRdLogo from '../assets/js_rd_logo.png';

type FilterType = 'all' | EntryType;

const PAGE_SIZE = 6;

/* ── Animated counter hook ── */
function useAnimatedCounter(target: number, duration = 1200) {
  const [count, setCount] = useState(0);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    if (target === 0) { setCount(0); return; }
    const start = performance.now();
    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.round(eased * target));
      if (progress < 1) frameRef.current = requestAnimationFrame(animate);
    };
    frameRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frameRef.current);
  }, [target, duration]);

  return count;
}

/* ── Floating particles component ── */
const Particles: React.FC = () => {
  const count = 40;
  const particles = useMemo(() =>
    Array.from({ length: count }, (_, i) => ({
      id: i,
      x: Math.random() * 100,
      y: Math.random() * 100,
      size: Math.random() * 2.5 + 0.8,
      duration: Math.random() * 25 + 18,
      delay: Math.random() * -30,
      opacity: Math.random() * 0.4 + 0.1,
    })), []);

  return (
    <div className="particles-container" aria-hidden="true">
      {particles.map(p => (
        <div
          key={p.id}
          className="particle"
          style={{
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: `${p.size}px`,
            height: `${p.size}px`,
            opacity: p.opacity,
            animationDuration: `${p.duration}s`,
            animationDelay: `${p.delay}s`,
          }}
        />
      ))}
    </div>
  );
};

export const Dashboard: React.FC = () => {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<FilterType>('all');
  const [selectedEntry, setSelectedEntry] = useState<Entry | null>(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const spotlightRef = useRef<HTMLDivElement>(null);

  /* cursor spotlight */
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (spotlightRef.current) {
      spotlightRef.current.style.setProperty('--mx', `${e.clientX}px`);
      spotlightRef.current.style.setProperty('--my', `${e.clientY}px`);
    }
  }, []);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      const data = await fetchEntries();
      setEntries(data);
      setLoading(false);
    };
    loadData();
  }, []);

  useEffect(() => { setVisibleCount(PAGE_SIZE); }, [activeFilter, searchQuery]);

  const filteredEntries = useMemo(() => {
    let result = entries;
    if (activeFilter !== 'all') result = result.filter(e => e.type === activeFilter);
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(e =>
        e.title.toLowerCase().includes(q) ||
        e.content.toLowerCase().includes(q) ||
        (e.teacher && e.teacher.toLowerCase().includes(q))
      );
    }
    return result;
  }, [entries, activeFilter, searchQuery]);

  const visibleEntries = filteredEntries.slice(0, visibleCount);
  const hasMore = visibleCount < filteredEntries.length;

  const diaryCount = useAnimatedCounter(entries.filter(e => e.type === 'diary').length);
  const worksheetCount = useAnimatedCounter(entries.filter(e => e.type === 'worksheet').length);
  const announcementCount = useAnimatedCounter(entries.filter(e => e.type === 'announcement').length);

  if (loading) {
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

  const filters: { key: FilterType; label: string; icon: React.ReactNode }[] = [
    { key: 'all', label: 'All Entries', icon: <Sparkles size={13} /> },
    { key: 'diary', label: 'Diary', icon: <Book size={13} /> },
    { key: 'worksheet', label: 'Worksheets', icon: <FileText size={13} /> },
    { key: 'announcement', label: 'Announcements', icon: <Bell size={13} /> },
  ];

  return (
    <div className="app-wrapper" ref={spotlightRef} onMouseMove={handleMouseMove}>
      {/* Cursor spotlight */}
      <div className="cursor-spotlight" />

      {/* Floating particles */}
      <Particles />

      {/* Aurora bands */}
      <div className="aurora" aria-hidden="true">
        <div className="aurora-band a1" />
        <div className="aurora-band a2" />
        <div className="aurora-band a3" />
      </div>

      {/* Noise texture overlay */}
      <div className="noise-overlay" />

      <div className="app-container">
        {/* Header */}
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
                      <stop offset="1" stopColor="#c084fc" />
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
          </div>
        </header>

        {/* Stats */}
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

        {/* Search */}
        <div className="search-container">
          <div className="search-glow" />
          <input
            id="search-bar"
            type="text"
            className="search-bar"
            placeholder="Search by subject, teacher, or keyword..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <Search size={18} className="search-icon" />
        </div>

        {/* Filters */}
        <div className="filter-tabs">
          {filters.map(f => (
            <button
              key={f.key}
              className={`filter-tab ${activeFilter === f.key ? 'active' : ''}`}
              onClick={() => setActiveFilter(f.key)}
            >
              {f.icon}
              {f.label}
            </button>
          ))}
        </div>

        {/* Grid */}
        <div className="entries-grid">
          {filteredEntries.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon-wrapper">
                <Inbox size={40} />
              </div>
              <p>No entries match your search.</p>
            </div>
          ) : (
            visibleEntries.map((entry, i) => (
              <EntryCard
                key={entry.id}
                entry={entry}
                onClick={setSelectedEntry}
                index={i}
              />
            ))
          )}
        </div>

        {/* View More */}
        {hasMore && (
          <div className="view-more-container">
            <button
              className="view-more-btn"
              onClick={() => setVisibleCount(prev => prev + PAGE_SIZE)}
            >
              <ChevronDown size={16} className="view-more-chevron" />
              View More
              <span className="view-more-count">
                {filteredEntries.length - visibleCount} remaining
              </span>
            </button>
          </div>
        )}

        {/* Footer */}
        <footer className="dashboard-footer">
          <div className="footer-content">
            <div className="footer-left">
              <span className="footer-label">Made by</span>
              <div className="company-info-wrapper">
                <img src={jsRdLogo} alt="J's R&D" className="company-logo-img" />
                <div className="company-text-wrapper">
                  <span className="company-name">J's R&D</span>
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
                  <path d="M107.7,8.07A105.15,105.15,0,0,0,77.26,0a77.19,77.19,0,0,0-3.3,6.83A96.67,96.67,0,0,0,53.22,6.83,77.19,77.19,0,0,0,49.88,0,105.15,105.15,0,0,0,19.44,8.07C3.66,31.58-1.86,54.65,1,77.53A105.73,105.73,0,0,0,32,96.36a77.7,77.7,0,0,0,6.63-10.85,68.43,68.43,0,0,1-10.45-5c.87-.64,1.72-1.32,2.53-2a75.46,75.46,0,0,0,72.77,0c.81.7,1.66,1.38,2.53,2a68.61,68.61,0,0,1-10.45,5,78.5,78.5,0,0,0,6.63,10.85,105.73,105.73,0,0,0,31.06-18.83C129.86,48.86,123.63,26,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53S36.18,40.36,42.45,40.36,53.83,46,53.83,53,48.72,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.24,60,73.24,53S78.41,40.36,84.69,40.36,96.07,46,96.07,53,91,65.69,84.69,65.69Z"/>
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
