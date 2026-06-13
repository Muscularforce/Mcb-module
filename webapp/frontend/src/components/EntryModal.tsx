import React, { useEffect, useCallback } from 'react';
import { Entry } from '../types';
import { X, Book, FileText, Bell, Calendar, User, Download, Paperclip } from 'lucide-react';

interface Props {
  entry: Entry | null;
  onClose: () => void;
}

export const EntryModal: React.FC<Props> = ({ entry, onClose }) => {
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    if (entry) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [entry, handleKeyDown]);

  const getIcon = (type: string) => {
    switch (type) {
      case 'diary': return <Book size={24} />;
      case 'worksheet': return <FileText size={24} />;
      case 'announcement': return <Bell size={24} />;
      default: return <Book size={24} />;
    }
  };

  const getLabel = (type: string) => {
    switch (type) {
      case 'diary': return 'Diary Entry';
      case 'worksheet': return 'Worksheet';
      case 'announcement': return 'Announcement';
      default: return 'Entry';
    }
  };

  return (
    <div
      className={`modal-overlay ${entry ? 'open' : ''}`}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {entry && (
        <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
          <div className={`modal-accent-bar ${entry.type}`} />

          <button className="modal-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>

          <div className="modal-header">
            <div className={`modal-icon ${entry.type}`}>
              {getIcon(entry.type)}
            </div>
            <div className="modal-header-text">
              <div className={`entry-badge ${entry.type}`} style={{ marginBottom: 10 }}>
                {getLabel(entry.type)}
              </div>
              <h2 className="modal-title">{entry.title}</h2>
              <div className="modal-meta">
                {entry.teacher && (
                  <span className="modal-meta-item">
                    <User size={14} />
                    {entry.teacher}
                  </span>
                )}
                <span className="modal-meta-item">
                  <Calendar size={14} />
                  {new Date(entry.date).toLocaleDateString('en-US', {
                    weekday: 'long',
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                  })}
                </span>
              </div>
            </div>
          </div>

          <div className="modal-body">
            <div className="modal-section-title">Details</div>
            <p className="modal-content-text">{entry.content}</p>

            <div className="modal-section-title">Attachment</div>
            {entry.attachment_url ? (
              <a
                href={entry.attachment_url}
                target="_blank"
                rel="noopener noreferrer"
                className="modal-download-btn"
              >
                <Download size={18} />
                Download / Open File
              </a>
            ) : (
              <div className="modal-no-attachment">
                <Paperclip size={16} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                No attachment available for this entry
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
