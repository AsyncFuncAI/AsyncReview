// Types matching backend DTOs

export interface PRFile {
  path: string
  status: 'added' | 'modified' | 'removed' | 'renamed'
  additions?: number
  deletions?: number
}

export interface PRInfo {
  reviewId: string
  title: string
  body: string
  repo: { owner: string; repo: string }
  number: number
  baseSha: string
  headSha: string
  files: PRFile[]
  user?: { login: string; avatar_url: string }
  state?: string
  draft?: boolean
  headRef?: string
  baseRef?: string
  commits?: number
  additions?: number
  deletions?: number
  changedFiles?: number
  commitsList?: Array<{
    sha: string
    message: string
    author: {
      name: string
      date: string
      login?: string
      avatar_url?: string
    }
    html_url: string
  }>
  comments?: Array<{
    id: number
    user: {
      login: string
      avatar_url: string
    }
    body: string
    created_at: string
    html_url: string
  }>
}

export interface FileContents {
  name: string
  contents: string
  cacheKey?: string
}

export interface FileContentsResponse {
  oldFile: FileContents | null
  newFile: FileContents | null
}

export interface RLMIteration {
  iteration: number
  maxIterations: number
  reasoning: string
  code: string
  output: string | null
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  iterations?: RLMIteration[]
}

export interface AnswerBlock {
  type: 'markdown' | 'code'
  content: string
  language?: string
}

export interface DiffCitation {
  path: string
  side: 'additions' | 'deletions'
  startLine: number
  endLine: number
  label?: string
  reason?: string
}

export interface DiffSelection {
  path: string
  side: 'additions' | 'deletions' | 'unified'
  startLine: number
  endLine: number
  mode: 'range' | 'single-line' | 'hunk' | 'file' | 'changeset'
}


export interface ReviewIssue {
  title: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  category: 'bug' | 'investigation' | 'informational'
  explanationMarkdown: string
  citations: DiffCitation[]
  fix_suggestions?: string[]
  tests_to_add?: string[]
}
