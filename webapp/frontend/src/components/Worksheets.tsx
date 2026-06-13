import React from 'react';
import { Entry } from '../types';
import { FileText } from 'lucide-react';

interface Props {
  entries: Entry[];
}

export const Worksheets: React.FC<Props> = ({ entries }) => {
  return (
    <div className="glass-panel">
      <h2 className="card-title">
        <FileText size={28} />
        Worksheets
      </h2>
      <div className="item-list">
        {entries.length === 0 ? (
          <p className="item-content">No worksheets found.</p>
        ) : (
          entries.map(entry => (
            <div key={entry.id} className="item">
              <div className="item-header">
                <div className="item-title">{entry.title}</div>
                <div className="item-date">{new Date(entry.date).toLocaleDateString()}</div>
              </div>
              <div className="item-content">{entry.content}</div>
              {entry.attachment_url && (
                <a href={entry.attachment_url} target="_blank" rel="noopener noreferrer" className="download-link">
                  Download Attachment
                </a>
              )}
              <div className="badge worksheet">Worksheet</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
