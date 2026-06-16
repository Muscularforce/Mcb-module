import React, { useRef, useCallback } from 'react';
import { Entry } from '../types';
import { Book, FileText, Bell, Calendar, User, Paperclip, ArrowUpRight } from 'lucide-react';

interface Props {
  entry: Entry;
  onClick: (entry: Entry) => void;
  index?: number;
}

export const EntryCard: React.FC<Props> = ({ entry, onClick, index = 0 }) => {
  const cardRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);

  const isAnswerKey = entry.type === 'worksheet' &&
    (entry.title.toLowerCase().includes('answerkey') ||
     entry.title.toLowerCase().includes('answer key') ||
     entry.title.toLowerCase().includes(' ak') ||
     entry.title.endsWith(' AK') ||
     entry.title.toLowerCase().includes('ans key') ||
     entry.title.toLowerCase().includes('anskey'));

  /* 3D tilt + glow follow on mouse move */
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const card = cardRef.current;
    const glow = glowRef.current;
    if (!card || !glow) return;
    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const rotateX = ((y - cy) / cy) * -7;
    const rotateY = ((x - cx) / cx) * 7;
    card.style.transform = `perspective(900px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.03,1.03,1.03)`;
    glow.style.background = `radial-gradient(600px circle at ${x}px ${y}px, rgba(99,102,241,0.12), transparent 40%)`;
  }, []);

  const handleMouseLeave = useCallback(() => {
    const card = cardRef.current;
    const glow = glowRef.current;
    if (card) card.style.transform = '';
    if (glow) glow.style.background = 'transparent';
  }, []);

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

  const formattedDate = new Date(entry.date).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric',
  });

  return (
    <div
      ref={cardRef}
      className={`entry-card ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}
      style={{ animationDelay: `${index * 60}ms` } as React.CSSProperties}
      onClick={() => onClick(entry)}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {/* Mouse-following inner glow */}
      <div ref={glowRef} className="card-glow-follow" />

      {/* Animated gradient border */}
      <div className="card-gradient-border" />

      {/* Shimmer sweep */}
      <div className="card-shimmer" />

      {/* Sparkle dots */}
      <div className="card-sparkle s1" />
      <div className="card-sparkle s2" />
      <div className="card-sparkle s3" />

      {/* Content */}
      <div className="card-inner">
        {/* Top: type pill + attachment indicator */}
        <div className="card-top">
          <span className={`card-type-pill ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}>
            {getIcon(entry.type)}
            {getLabel(entry.type)}
          </span>
          <div className="card-top-right">
            {entry.attachment_url && (
              <span className="card-attach-indicator" title="Has attachment">
                <Paperclip size={11} />
              </span>
            )}
            <span className="card-date-chip">
              <Calendar size={10} />
              {formattedDate}
            </span>
          </div>
        </div>

        {/* Title */}
        <h3 className="card-title">{entry.title}</h3>

        {/* Teacher chip */}
        {entry.teacher && (
          <div className="card-teacher">
            <User size={11} />
            <span>{entry.teacher}</span>
          </div>
        )}

        {/* Content preview */}
        <p className="card-preview">{entry.content}</p>

        {/* Footer CTA */}
        <div className="card-footer">
          {entry.attachment_url ? (
            <span className="card-attach-badge">
              <Paperclip size={11} />
              File attached
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
