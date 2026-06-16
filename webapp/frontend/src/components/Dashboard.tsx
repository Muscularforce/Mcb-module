import React, { useEffect, useState, useMemo } from 'react';
import { fetchEntries } from '../api';
import { Entry, EntryType } from '../types';
import { EntryCard } from './EntryCard';
import { EntryModal } from './EntryModal';
import { Search, Book, FileText, Bell, Inbox } from 'lucide-react';

type FilterType = 'all' | EntryType;

export const Dashboard: React.FC = () => {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<FilterType>('all');
  const [selectedEntry, setSelectedEntry] = useState<Entry | null>(null);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      const data = await fetchEntries();
      setEntries(data);
      setLoading(false);
    };
    loadData();
  }, []);

  const filteredEntries = useMemo(() => {
    let result = entries;

    if (activeFilter !== 'all') {
      result = result.filter(e => e.type === activeFilter);
    }

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

  const counts = useMemo(() => ({
    diary: entries.filter(e => e.type === 'diary').length,
    worksheet: entries.filter(e => e.type === 'worksheet').length,
    announcement: entries.filter(e => e.type === 'announcement').length,
  }), [entries]);

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner" />
        <span className="loading-text">Loading your dashboard...</span>
      </div>
    );
  }

  const filters: { key: FilterType; label: string }[] = [
    { key: 'all', label: 'All Entries' },
    { key: 'diary', label: 'Diary' },
    { key: 'worksheet', label: 'Worksheets' },
    { key: 'announcement', label: 'Announcements' },
  ];

  return (
    <div className="app-container">
      {/* Header */}
      <header className="header">
        <div className="header-logo-container">
          <div className="header-logo-wrapper">
            <svg viewBox="0 0 24 24" className="mcb-logo-svg" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="url(#logo-grad-1)" />
              <path d="M2 17L12 22L22 17" stroke="url(#logo-grad-2)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M2 12L12 17L22 12" stroke="url(#logo-grad-1)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <defs>
                <linearGradient id="logo-grad-1" x1="2" y1="2" x2="22" y2="17" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#3b82f6" />
                  <stop offset="1" stopColor="#8b5cf6" />
                </linearGradient>
                <linearGradient id="logo-grad-2" x1="2" y1="12" x2="22" y2="22" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#f59e0b" />
                  <stop offset="1" stopColor="#ef4444" />
                </linearGradient>
              </defs>
            </svg>
            <div className="mcb-logo-text">
              <span className="logo-my">my</span>
              <span className="logo-classboard">classboard</span>
            </div>
          </div>
        </div>
        <p className="header-subtitle">Rainbow International School - Student Portal Hub</p>
      </header>

      {/* Stats */}
      <div className="stats-bar">
        <div className="stat-item">
          <div className="stat-icon diary"><Book size={18} /></div>
          <div>
            <div className="stat-number">{counts.diary}</div>
            <div className="stat-label">Diary</div>
          </div>
        </div>
        <div className="stat-item">
          <div className="stat-icon worksheet"><FileText size={18} /></div>
          <div>
            <div className="stat-number">{counts.worksheet}</div>
            <div className="stat-label">Worksheets</div>
          </div>
        </div>
        <div className="stat-item">
          <div className="stat-icon announcement"><Bell size={18} /></div>
          <div>
            <div className="stat-number">{counts.announcement}</div>
            <div className="stat-label">Announcements</div>
          </div>
        </div>
      </div>

      {/* Search */}
      <div className="search-container">
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
            {f.label}
          </button>
        ))}
      </div>

      {/* Grid */}
      <div className="entries-grid">
        {filteredEntries.length === 0 ? (
          <div className="empty-state">
            <Inbox size={48} />
            <p>No entries match your search or filter.</p>
          </div>
        ) : (
          filteredEntries.map(entry => (
            <EntryCard
              key={entry.id}
              entry={entry}
              onClick={setSelectedEntry}
            />
          ))
        )}
      </div>

      {/* Modal */}
      <EntryModal entry={selectedEntry} onClose={() => setSelectedEntry(null)} />
    </div>
  );
};
