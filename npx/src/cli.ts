/**
 * Main CLI handler for the review command
 */

import chalk from 'chalk';
import ora from 'ora';
import { getApiKey, getGitHubToken } from './api-key.js';
import {
    checkPython,
    checkDeno,
    installDeno,
    checkAsyncReviewInstalled,
    installAsyncReview,
    runPythonReview
} from './python-runner.js';

export interface ReviewOptions {
    url?: string;
    path?: string;
    question?: string;
    output: string;
    quiet?: boolean;
    model?: string;
    api?: string;
    githubToken?: string;
    expert?: boolean;
}

export async function runReview(options: ReviewOptions): Promise<void> {
    const { url, path, question, output, quiet = false, model, api, githubToken, expert = false } = options;

    try {

        // 4. Get API key
        const apiKey = await getApiKey(api);

        // 5. Get GitHub token only if using URL mode (not required for local path mode)
        let ghToken: string | undefined;
        if (url) {
            ghToken = await getGitHubToken(githubToken, true);
        }

        // 6. Run the review
        if (!quiet) {
            const target = url || path;
            console.log(chalk.cyan(`\n 🔍 Reviewing: ${target}`));
            if (expert) {
                console.log(chalk.cyan(`   Mode: Expert Code Review (SOLID, Security, Code Quality)\n`));
            } else if (question) {
                console.log(chalk.dim(`   Question: ${question}\n`));
            }
        }

        const result = await runPythonReview({
            url,
            path,
            question,
            output,
            quiet,
            model,
            apiKey,
            githubToken: ghToken,
            expert,
        });

        // In quiet mode, we suppressed stdout during execution
        // So we must print the final result now
        if (quiet && result.trim()) {
            console.log(result);
        }

    } catch (error) {
        if (error instanceof Error) {
            console.error(chalk.red(`\nError: ${error.message}`));
        } else {
            console.error(chalk.red('\nAn unexpected error occurred'));
        }
        process.exit(1);
    }
}
