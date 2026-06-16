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

  const isAnswerKey = entry && entry.type === 'worksheet' && 
    (entry.title.toLowerCase().includes('answerkey') || 
     entry.title.toLowerCase().includes('answer key') || 
     entry.title.toLowerCase().includes(' ak') || 
     entry.title.endsWith(' AK') ||
     entry.title.toLowerCase().includes('ans key') || 
     entry.title.toLowerCase().includes('anskey'));

  const getLabel = (type: string) => {
    if (isAnswerKey) return 'Answer Key';
    switch (type) {
      case 'diary': return 'Diary Entry';
      case 'worksheet': return 'Worksheet';
      case 'announcement': return 'Announcement';
      default: return 'Entry';
    }
  };

  const getAttachmentDetails = (url: string | undefined) => {
    if (!url) return { filename: 'file', ext: 'FILE', colorClass: 'file' };
    const filename = decodeURIComponent(url.split('/').pop() || 'file');
    const ext = filename.split('.').pop()?.toLowerCase() || 'file';
    
    let label = 'FILE';
    let colorClass = 'file';
    
    if (['pdf'].includes(ext)) {
      label = 'PDF';
      colorClass = 'pdf';
    } else if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) {
      label = 'IMAGE';
      colorClass = 'image';
    } else if (['doc', 'docx'].includes(ext)) {
      label = 'WORD';
      colorClass = 'word';
    } else if (['xls', 'xlsx'].includes(ext)) {
      label = 'EXCEL';
      colorClass = 'excel';
    } else if (['ppt', 'pptx'].includes(ext)) {
      label = 'POWERPOINT';
      colorClass = 'ppt';
    }
    
    return { filename, ext: label, colorClass };
  };

  return (
    <div
      className={`modal-overlay ${entry ? 'open' : ''}`}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {entry && (
        <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
          <div className={`modal-accent-bar ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`} />

          <button className="modal-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>

          <div className="modal-header">
            <div className={`modal-icon ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}>
              {getIcon(entry.type)}
            </div>
            <div className="modal-header-text">
              <div className={`entry-badge ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`} style={{ marginBottom: 10 }}>
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
            {entry.attachment_url ? (() => {
              const { filename, ext, colorClass } = getAttachmentDetails(entry.attachment_url);
              return (
                <div className={`attachment-card ${colorClass}`}>
                  <div className="attachment-icon-wrapper">
                    <FileText size={24} className="attachment-icon" />
                    <span className="attachment-badge">{ext}</span>
                  </div>
                  <div className="attachment-info">
                    <div className="attachment-filename" title={filename}>
                      {filename}
                    </div>
                    <div className="attachment-source">
                      MyClassboard Secure CDN Document
                    </div>
                  </div>
                  <div className="attachment-actions">
                    <a
                      href={entry.attachment_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="attachment-action-btn view"
                    >
                      View
                    </a>
                    <a
                      href={entry.attachment_url}
                      download
                      target="_blank"
                      rel="noopener noreferrer"
                      className="attachment-action-btn download"
                      title="Download File"
                    >
                      <Download size={14} />
                    </a>
                  </div>
                </div>
              );
            })() : (
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
