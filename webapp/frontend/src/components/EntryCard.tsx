import React from 'react';
import { Entry } from '../types';
import { Book, FileText, Bell, Calendar, User, Paperclip, ArrowRight } from 'lucide-react';

interface Props {
  entry: Entry;
  onClick: (entry: Entry) => void;
  index?: number;
}

export const EntryCard: React.FC<Props> = ({ entry, onClick, index = 0 }) => {
  const isAnswerKey = entry.type === 'worksheet' &&
    (entry.title.toLowerCase().includes('answerkey') ||
     entry.title.toLowerCase().includes('answer key') ||
     entry.title.toLowerCase().includes(' ak') ||
     entry.title.endsWith(' AK') ||
     entry.title.toLowerCase().includes('ans key') ||
     entry.title.toLowerCase().includes('anskey'));

  const getIcon = (type: string) => {
    switch (type) {
      case 'diary': return <Book size={14} />;
      case 'worksheet': return <FileText size={14} />;
      case 'announcement': return <Bell size={14} />;
      default: return <Book size={14} />;
    }
  };

  const getLabel = (type: string) => {
    if (isAnswerKey) return 'Answer Key';
    switch (type) {
      case 'diary': return 'Diary';
      case 'worksheet': return 'Worksheet';
      case 'announcement': return 'Announcement';
      default: return 'Entry';
    }
  };

  const formattedDate = new Date(entry.date).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric'
  });

  return (
    <div
      className={`entry-card ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}
      style={{ animationDelay: `${index * 55}ms` }}
      onClick={() => onClick(entry)}
    >
      {/* Animated gradient border ring */}
      <div className="card-border-ring" />

      {/* Shimmer sweep on hover */}
      <div className="card-shimmer" />

      {/* Top section */}
      <div className="card-top">
        <span className={`card-type-pill ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}>
          {getIcon(entry.type)}
          {getLabel(entry.type)}
        </span>
        {entry.attachment_url && (
          <span className="card-attach-dot" title="Has attachment">
            <Paperclip size={11} />
          </span>
        )}
      </div>

      {/* Title */}
      <h3 className="card-title">{entry.title}</h3>

      {/* Meta chips */}
      <div className="card-meta-row">
        {entry.teacher && (
          <span className="meta-chip">
            <User size={11} />
            {entry.teacher}
          </span>
        )}
        <span className="meta-chip">
          <Calendar size={11} />
          {formattedDate}
        </span>
      </div>

      {/* Content preview */}
      <p className="card-preview">{entry.content}</p>

      {/* Footer */}
      <div className="card-footer">
        {entry.attachment_url ? (
          <span className="card-attach-badge">
            <Paperclip size={12} />
            Attachment
          </span>
        ) : <span />}
        <span className="card-cta">
          View details
          <ArrowRight size={13} />
        </span>
      </div>
    </div>
  );
};
