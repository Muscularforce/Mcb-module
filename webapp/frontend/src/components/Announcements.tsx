import React from 'react';
import type { Entry } from '../types';
import { formatLocalDate, getSafeAttachments } from '../lib/entries.ts';
import { Bell } from 'lucide-react';

interface Props {
  entries: Entry[];
}

export const Announcements: React.FC<Props> = ({ entries }) => {
  return (
    <div className="glass-panel">
      <h2 className="card-title">
        <Bell size={28} />
        Announcements
      </h2>
      <div className="item-list">
        {entries.length === 0 ? (
          <p className="item-content">No announcements right now.</p>
        ) : (
          entries.map(entry => {
            const attachments = getSafeAttachments(entry.attachments, entry.attachment_url);
            return (
              <div key={entry.id} className="item">
                <div className="item-header">
                  <div className="item-title">{entry.title}</div>
                  <div className="item-date">{formatLocalDate(entry.date)}</div>
                </div>
                <div className="item-content">{entry.content}</div>
                {attachments.length > 0 && (
                  <div className="download-links">
                    {attachments.map(attachment => (
                      <a key={attachment.url} href={attachment.url} download={attachment.name} target="_blank" rel="noopener noreferrer" className="download-link">
                        Download {attachment.name}
                      </a>
                    ))}
                  </div>
                )}
                <div className="badge announcement">Announcement</div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
