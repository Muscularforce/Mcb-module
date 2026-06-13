import React, { useEffect, useState, useMemo } from 'react';
import { fetchEntries } from '../api';
import { Entry, EntryType } from '../types';
import { EntryCard } from './EntryCard';
import { EntryModal } from './EntryModal';
import { GraduationCap, Search, Book, FileText, Bell, Inbox } from 'lucide-react';

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
        <div className="header-logo">
          <GraduationCap size={32} />
        </div>
        <h1>MCB Dashboard</h1>
        <p className="header-subtitle">Your centralized hub for learning and updates</p>
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
