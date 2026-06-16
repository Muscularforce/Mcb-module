import React, { useEffect, useState, useMemo } from 'react';
import { fetchEntries } from '../api';
import { Entry, EntryType } from '../types';
import { EntryCard } from './EntryCard';
import { EntryModal } from './EntryModal';
import { Search, Book, FileText, Bell, Inbox } from 'lucide-react';
import jsRdLogo from '../assets/js_rd_logo.png';

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
        <div className="header-top-branding">
          <span className="header-brand-by">Made by</span>
          <a href="https://discord.gg/966WM3djK" target="_blank" rel="noopener noreferrer" className="header-brand-link" title="Join J's R&D Discord Server">
            <img src={jsRdLogo} alt="J's R&D" className="header-brand-logo" />
            <span className="header-brand-name">J's R&D</span>
          </a>
        </div>

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
            <a href="https://discord.gg/966WM3djK" target="_blank" rel="noopener noreferrer" className="discord-link-btn">
              <svg viewBox="0 0 127.14 96.36" className="discord-icon-svg" fill="currentColor">
                <path d="M107.7,8.07A105.15,105.15,0,0,0,77.26,0a77.19,77.19,0,0,0-3.3,6.83A96.67,96.67,0,0,0,53.22,6.83,77.19,77.19,0,0,0,49.88,0,105.15,105.15,0,0,0,19.44,8.07C3.66,31.58-1.86,54.65,1,77.53A105.73,105.73,0,0,0,32,96.36a77.7,77.7,0,0,0,6.63-10.85,68.43,68.43,0,0,1-10.45-5c.87-.64,1.72-1.32,2.53-2a75.46,75.46,0,0,0,72.77,0c.81.7,1.66,1.38,2.53,2a68.61,68.61,0,0,1-10.45,5,78.5,78.5,0,0,0,6.63,10.85,105.73,105.73,0,0,0,31.06-18.83C129.86,48.86,123.63,26,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53S36.18,40.36,42.45,40.36,53.83,46,53.83,53,48.72,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.24,60,73.24,53S78.41,40.36,84.69,40.36,96.07,46,96.07,53,91,65.69,84.69,65.69Z"/>
              </svg>
              <span>Join Discord Server</span>
            </a>
          </div>
        </div>
      </footer>

      {/* Modal */}
      <EntryModal entry={selectedEntry} onClose={() => setSelectedEntry(null)} />
    </div>
  );
};
