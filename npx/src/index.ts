#!/usr/bin/env node
/**
 * AsyncReview CLI - AI-powered GitHub PR/Issue reviews
 * 
 * Usage:
 *   npx asyncreview review --url https://github.com/org/repo/pull/123 -q "Any risks?"
 */

import { program } from 'commander';
import { runReview } from './cli.js';

program
    .name('asyncreview')
    .description('AI-powered GitHub PR/Issue reviews from the command line')
    .version('0.1.0');

program
    .command('review')
    .description('Review a GitHub PR/Issue or local directory')
    .option('-u, --url <url>', 'GitHub PR or Issue URL')
    .option('-p, --path <path>', 'Local directory path to review')
    .option('-q, --question <question>', 'Question to ask about the PR/Issue (optional with --expert)')
    .option('--expert', 'Run expert code review (SOLID, Security, Performance, Code Quality)')
    .option('-o, --output <format>', 'Output format: text, markdown, json', 'text')
    .option('--quiet', 'Suppress progress output')
    .option('-m, --model <model>', 'Model to use (e.g. gemini-3-pro-preview)')
    .option('--api <key>', 'Gemini API key (defaults to GEMINI_API_KEY env var)')
    .option('--github-token <token>', 'GitHub token for private repos (defaults to GITHUB_TOKEN env var)')
    .action(async (options) => {
        // Validate mutual exclusion: exactly one of --url or --path must be provided
        if (!options.url && !options.path) {
            console.error('Error: Either --url or --path must be provided');
            process.exit(1);
        }
        if (options.url && options.path) {
            console.error('Error: --url and --path are mutually exclusive');
            process.exit(1);
        }
        await runReview(options);
    });

program.parse();
