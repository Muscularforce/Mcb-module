import React, { useCallback, useRef } from 'react';
import type { Entry } from '../types';
import { formatLocalDate, getSafeAttachments, isAnswerKeyEntry } from '../lib/entries.ts';
import { ArrowUpRight, Bell, Book, Calendar, FileText, Paperclip, User } from 'lucide-react';

interface Props {
  entry: Entry;
  onClick: (entry: Entry) => void;
  index?: number;
}

export const EntryCard: React.FC<Props> = ({ entry, onClick, index = 0 }) => {
  const cardRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const isAnswerKey = isAnswerKeyEntry(entry);
  const attachmentCount = getSafeAttachments(entry.attachments, entry.attachment_url).length;

  const handleMouseMove = useCallback((event: React.MouseEvent) => {
    const card = cardRef.current;
    const glow = glowRef.current;
    if (!card || !glow) return;
    const rect = card.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;
    const rotateX = ((y - centerY) / centerY) * -7;
    const rotateY = ((x - centerX) / centerX) * 7;
    card.style.transform = `perspective(900px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.03,1.03,1.03)`;
    glow.style.background = `radial-gradient(600px circle at ${x}px ${y}px, rgba(99,102,241,0.12), transparent 40%)`;
  }, []);

  const handleMouseLeave = useCallback(() => {
    if (cardRef.current) cardRef.current.style.transform = '';
    if (glowRef.current) glowRef.current.style.background = 'transparent';
  }, []);

  const handleKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    onClick(entry);
  }, [entry, onClick]);

  const getIcon = (type: string) => {
    switch (type) {
      case 'diary': return <Book size={13} />;
      case 'worksheet': return <FileText size={13} />;
      case 'announcement': return <Bell size={13} />;
      default: return <Book size={13} />;
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

  return (
    <div
      ref={cardRef}
      className={`entry-card ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}
      style={{ animationDelay: `${index * 60}ms` } as React.CSSProperties}
      role="button"
      tabIndex={0}
      aria-haspopup="dialog"
      aria-label={`Open ${entry.title}`}
      onClick={() => onClick(entry)}
      onKeyDown={handleKeyDown}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <div ref={glowRef} className="card-glow-follow" />
      <div className="card-gradient-border" />
      <div className="card-shimmer" />
      <div className="card-sparkle s1" />
      <div className="card-sparkle s2" />
      <div className="card-sparkle s3" />

      <div className="card-inner">
        <div className="card-top">
          <div className="card-label-group">
            <span className={`card-type-pill ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}>
              {getIcon(entry.type)}
              {getLabel(entry.type)}
            </span>
            {entry.label && (
              <span className="card-portal-label" title={`Portal label: ${entry.label}`}>
                {entry.label}
              </span>
            )}
          </div>
          <div className="card-top-right">
            {attachmentCount > 0 && (
              <span className="card-attach-indicator" title={`${attachmentCount} attachment${attachmentCount === 1 ? '' : 's'}`}>
                <Paperclip size={11} />
                <span>{attachmentCount}</span>
              </span>
            )}
            <span className="card-date-chip">
              <Calendar size={10} />
              {formatLocalDate(entry.date)}
            </span>
          </div>
        </div>

        <h3 className="card-title">{entry.title}</h3>

        {entry.teacher && (
          <div className="card-teacher">
            <User size={11} />
            <span>{entry.teacher}</span>
          </div>
        )}

        <p className="card-preview">{entry.content}</p>

        <div className="card-footer">
          {attachmentCount > 0 ? (
            <span className="card-attach-badge">
              <Paperclip size={11} />
              {attachmentCount} attachment{attachmentCount === 1 ? '' : 's'}
            </span>
          ) : <span />}
          <span className="card-cta">
            Open
            <ArrowUpRight size={13} />
          </span>
        </div>
      </div>
    </div>
  );
};
