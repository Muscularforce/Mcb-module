import React, { useEffect, useId, useRef } from 'react';
import type { Entry } from '../types';
import { formatLocalDate, getSafeAttachments, isAnswerKeyEntry } from '../lib/entries.ts';
import { Bell, Book, Calendar, Download, FileText, Paperclip, User, X } from 'lucide-react';

interface Props {
  entry: Entry | null;
  onClose: () => void;
}

export const EntryModal: React.FC<Props> = ({ entry, onClose }) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  const contentId = useId();
  const isOpen = entry !== null;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const activeElement = document.activeElement;
    previousFocusRef.current = activeElement instanceof HTMLElement ? activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusTimer = window.setTimeout(() => closeRef.current?.focus(), 0);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!panel.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      const previousFocus = previousFocusRef.current;
      if (previousFocus?.isConnected) previousFocus.focus();
      previousFocusRef.current = null;
    };
  }, [isOpen]);

  const getIcon = (type: string) => {
    switch (type) {
      case 'diary': return <Book size={24} />;
      case 'worksheet': return <FileText size={24} />;
      case 'announcement': return <Bell size={24} />;
      default: return <Book size={24} />;
    }
  };

  const isAnswerKey = entry ? isAnswerKeyEntry(entry) : false;
  const safeAttachments = entry ? getSafeAttachments(entry.attachments, entry.attachment_url) : [];

  const getLabel = (type: string) => {
    if (isAnswerKey) return 'Answer Key';
    switch (type) {
      case 'diary': return 'Diary Entry';
      case 'worksheet': return 'Worksheet';
      case 'announcement': return 'Announcement';
      default: return 'Entry';
    }
  };

  const getAttachmentDetails = (attachment: { name: string }) => {
    const filename = attachment.name || 'Attachment';
    const extension = filename.split('.').pop()?.toLowerCase() || '';
    let label = 'FILE';
    let colorClass = 'file';

    if (extension === 'pdf') {
      label = 'PDF';
      colorClass = 'pdf';
    } else if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(extension)) {
      label = 'IMAGE';
      colorClass = 'image';
    } else if (['doc', 'docx'].includes(extension)) {
      label = 'WORD';
      colorClass = 'word';
    } else if (['xls', 'xlsx'].includes(extension)) {
      label = 'EXCEL';
      colorClass = 'excel';
    } else if (['ppt', 'pptx'].includes(extension)) {
      label = 'POWERPOINT';
      colorClass = 'ppt';
    }

    return { filename, ext: label, colorClass };
  };

  return (
    <div
      className={`modal-overlay ${entry ? 'open' : ''}`}
      aria-hidden={!entry}
      onMouseDown={event => {
        if (event.target === event.currentTarget) onCloseRef.current();
      }}
    >
      {entry && (
        <div
          ref={panelRef}
          className="modal-panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={contentId}
          tabIndex={-1}
        >
          <div className={`modal-accent-bar ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`} />

          <button ref={closeRef} type="button" className="modal-close" onClick={() => onCloseRef.current()} aria-label="Close entry details">
            <X size={18} />
          </button>

          <div className="modal-header">
            <div className={`modal-icon ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}>
              {getIcon(entry.type)}
            </div>
            <div className="modal-header-text">
              <div className="modal-labels">
                <div className={`entry-badge ${entry.type} ${isAnswerKey ? 'answer-key' : ''}`}>
                  {getLabel(entry.type)}
                </div>
                {entry.label && (
                  <span className="modal-portal-label" title={`Portal label: ${entry.label}`}>
                    Portal: {entry.label}
                  </span>
                )}
              </div>
              <h2 id={titleId} className="modal-title">{entry.title}</h2>
              <div className="modal-meta">
                {entry.teacher && (
                  <span className="modal-meta-item">
                    <User size={14} />
                    {entry.teacher}
                  </span>
                )}
                <span className="modal-meta-item">
                  <Calendar size={14} />
                  {formatLocalDate(entry.date, {
                    weekday: 'long',
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                  })}
                </span>
              </div>
            </div>
          </div>

          <div className="modal-body">
            <div className="modal-section-title">Description</div>
            <p id={contentId} className="modal-content-text">{entry.content}</p>

            <div className="modal-section-title">
              {safeAttachments.length === 1 ? 'Attachment' : 'Attachments'}
            </div>
            {safeAttachments.length > 0 ? (
              <div className="attachment-list">
                {safeAttachments.map(attachment => {
                  const { filename, ext, colorClass } = getAttachmentDetails(attachment);
                  return (
                    <div className={`attachment-card ${colorClass}`} key={attachment.url}>
                      <div className="attachment-icon-wrapper">
                        <FileText size={24} className="attachment-icon" />
                        <span className="attachment-badge">{ext}</span>
                      </div>
                      <div className="attachment-info">
                        <div className="attachment-filename" title={filename}>
                          {filename}
                        </div>
                        <div className="attachment-source">MyClassboard document</div>
                      </div>
                      <div className="attachment-actions">
                        <a
                          href={attachment.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="attachment-action-btn view"
                          aria-label={`View ${filename}`}
                        >
                          View
                        </a>
                        <a
                          href={attachment.url}
                          download={filename}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="attachment-action-btn download"
                          aria-label={`Download ${filename}`}
                          title={`Download ${filename}`}
                        >
                          <Download size={14} />
                          <span>Download</span>
                        </a>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="modal-no-attachment">
                <Paperclip size={16} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                No trusted attachment available for this entry
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
