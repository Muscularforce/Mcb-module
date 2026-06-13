import React from 'react';
import { Entry } from '../types';
import { Book, FileText, Bell, Calendar, User, Paperclip, ArrowRight } from 'lucide-react';

interface Props {
  entry: Entry;
  onClick: (entry: Entry) => void;
}

export const EntryCard: React.FC<Props> = ({ entry, onClick }) => {
  const getIcon = (type: string) => {
    switch (type) {
      case 'diary': return <Book size={20} />;
      case 'worksheet': return <FileText size={20} />;
      case 'announcement': return <Bell size={20} />;
      default: return <Book size={20} />;
    }
  };

  const getLabel = (type: string) => {
    switch (type) {
      case 'diary': return 'Diary';
      case 'worksheet': return 'Worksheet';
      case 'announcement': return 'Announcement';
      default: return 'Entry';
    }
  };

  return (
    <div className={`entry-card ${entry.type}`} onClick={() => onClick(entry)}>
      <div className="entry-card-top">
        <div className={`entry-type-icon ${entry.type}`}>
          {getIcon(entry.type)}
        </div>
        <span className={`entry-badge ${entry.type}`}>
          {getLabel(entry.type)}
        </span>
      </div>

      <div className="entry-title">{entry.title}</div>

      <div className="entry-meta">
        {entry.teacher && (
          <span className="entry-meta-item">
            <User size={13} />
            {entry.teacher}
          </span>
        )}
        <span className="entry-meta-item">
          <Calendar size={13} />
          {new Date(entry.date).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric'
          })}
        </span>
      </div>

      <div className="entry-content">{entry.content}</div>

      <div className="entry-footer">
        {entry.attachment_url ? (
          <span className="attachment-indicator">
            <Paperclip size={14} />
            Attachment
          </span>
        ) : (
          <span />
        )}
        <span className="click-hint">
          View details <ArrowRight size={12} />
        </span>
      </div>
    </div>
  );
};
