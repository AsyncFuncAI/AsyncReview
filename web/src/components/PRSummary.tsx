import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { PRInfo } from '../types'

interface PRSummaryProps {
    prInfo: PRInfo | null
}

export function PRSummary({ prInfo }: PRSummaryProps) {
    const [activeTab, setActiveTab] = useState<'description' | 'discussion' | 'commits'>('description')

    if (!prInfo) return null

    return (
        <div className="pr-summary">
            {/* Header Info */}
            <div className="pr-header">
                <div className="pr-meta-top">
                    <span className={`pr-state ${prInfo.state || 'open'}`}>
                        {prInfo.draft ? 'Draft' : (prInfo.state || 'Open')}
                    </span>
                    <span className="pr-repo">{prInfo.repo.owner}/{prInfo.repo.repo} #{prInfo.number}</span>
                </div>

                <h1 className="pr-title">{prInfo.title}</h1>

                <div className="pr-meta-row">
                    {prInfo.user && (
                        <div className="pr-user">
                            {prInfo.user.avatar_url && (
                                <img src={prInfo.user.avatar_url} alt={prInfo.user.login} className="pr-avatar" />
                            )}
                            <span>{prInfo.user.login}</span>
                        </div>
                    )}

                    <div className="pr-branches">
                        <span className="branch-name">{prInfo.headRef || prInfo.headSha.substring(0, 7)}</span>
                        <span className="arrow">→</span>
                        <span className="branch-name">{prInfo.baseRef || prInfo.baseSha.substring(0, 7)}</span>
                    </div>

                    <div className="pr-stats">
                        <span>{prInfo.changedFiles ?? prInfo.files.length} files</span>
                        <span className="additions">+{prInfo.additions || 0}</span>
                        <span className="deletions">-{prInfo.deletions || 0}</span>
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <div className="pr-tabs">
                <button
                    className={`pr-tab ${activeTab === 'description' ? 'active' : ''}`}
                    onClick={() => setActiveTab('description')}
                >
                    Description
                </button>
                <button
                    className={`pr-tab ${activeTab === 'discussion' ? 'active' : ''}`}
                    onClick={() => setActiveTab('discussion')}
                >
                    Discussion {prInfo.comments && prInfo.comments.length > 0 && <span className="tab-count">{prInfo.comments.length}</span>}
                </button>
                <button
                    className={`pr-tab ${activeTab === 'commits' ? 'active' : ''}`}
                    onClick={() => setActiveTab('commits')}
                >
                    Commits {(prInfo.commits || 0) > 0 && <span className="tab-count">{prInfo.commits}</span>}
                </button>
            </div>

            {/* Tab Content */}
            <div className="pr-tab-content">
                {activeTab === 'description' && (
                    <div className="markdown-body">
                        {prInfo.body ? <ReactMarkdown>{prInfo.body}</ReactMarkdown> : <em style={{ color: 'var(--text-secondary)' }}>No description provided.</em>}
                    </div>
                )}

                {activeTab === 'discussion' && (
                    <div className="pr-discussion">
                        {prInfo.comments && prInfo.comments.length > 0 ? (
                            prInfo.comments.map(comment => (
                                <div key={comment.id} className="discussion-item">
                                    <div className="discussion-header">
                                        <div className="discussion-user">
                                            <img src={comment.user.avatar_url} alt={comment.user.login} className="discussion-avatar" />
                                            <span className="discussion-username">{comment.user.login}</span>
                                            <span className="discussion-time">{new Date(comment.created_at).toLocaleDateString()}</span>
                                        </div>
                                    </div>
                                    <div className="discussion-body markdown-body">
                                        <ReactMarkdown>{comment.body}</ReactMarkdown>
                                    </div>
                                </div>
                            ))
                        ) : (
                            <div className="empty-state">No comments yet.</div>
                        )}
                    </div>
                )}

                {activeTab === 'commits' && (
                    <div className="pr-commits-timeline">
                        {prInfo.commitsList && prInfo.commitsList.length > 0 ? (
                            prInfo.commitsList.map((commit) => (
                                <div key={commit.sha} className="timeline-item">
                                    {/* Line connecting items, except last one */}
                                    <div className="timeline-line"></div>
                                    <div className="timeline-marker"></div>
                                    <div className="commit-card">
                                        <div className="commit-header">
                                            <div className="commit-message">{commit.message.split('\n')[0]}</div>
                                            <div className="commit-meta">
                                                <div className="commit-author">
                                                    {commit.author.avatar_url ? (
                                                        <img src={commit.author.avatar_url} className="commit-avatar" alt="" />
                                                    ) : <div className="commit-avatar-placeholder" />}
                                                    <span className="commit-author-name">{commit.author.login || commit.author.name}</span>
                                                </div>
                                                <span className="commit-hash">{commit.sha.substring(0, 7)}</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ))
                        ) : (
                            <div className="empty-state">No commits found.</div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
