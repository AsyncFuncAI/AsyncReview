/**
 * API key and GitHub token management - handles env vars, CLI flags, and interactive prompts
 */

import inquirer from 'inquirer';
import chalk from 'chalk';

const LLM_API_KEY_VARS = ['GEMINI_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'];

function usesLocalProvider(model?: string): boolean {
    return !!model && (model.startsWith('ollama/') || model.startsWith('ollama_chat/'));
}

export async function getApiKey(cliApiKey?: string, model?: string): Promise<string | undefined> {
    // 1. Check --api flag first (highest priority)
    if (cliApiKey) {
        return cliApiKey;
    }

    // 2. Check provider-specific environment variables used by LiteLLM
    if (LLM_API_KEY_VARS.some((name) => process.env[name])) {
        return undefined;
    }

    if (usesLocalProvider(model)) {
        return undefined;
    }

    // 3. No API key found - prompt user
    console.log(chalk.yellow('\n⚠️  No LLM API key found.\n'));
    console.log(chalk.dim('You can set it via:'));
    console.log(chalk.dim('  • --api <key> flag for Gemini'));
    console.log(chalk.dim('  • GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY environment variable\n'));

    const answers = await inquirer.prompt([
        {
            type: 'password',
            name: 'apiKey',
            message: 'Enter your Gemini API key:',
            mask: '•',
            validate: (input: string) => {
                if (!input || input.trim().length === 0) {
                    return 'API key is required';
                }
                return true;
            },
        },
    ]);

    return answers.apiKey;
}

export async function getGitHubToken(cliToken?: string, requireToken: boolean = true): Promise<string> {
    const { spawnSync } = await import('child_process');

    // 1. Check --github-token flag first (highest priority)
    if (cliToken) {
        return cliToken;
    }

    // 2. Check environment variable
    const envToken = process.env.GITHUB_TOKEN;
    if (envToken) {
        return envToken;
    }

    // 3. Try to get token from GitHub CLI (gh auth token)
    try {
        const result = spawnSync('gh', ['auth', 'token'], {
            encoding: 'utf-8',
            timeout: 5000,
        });
        if (result.status === 0 && result.stdout.trim()) {
            const ghToken = result.stdout.trim();
            // Silently use the token from gh CLI
            return ghToken;
        }
    } catch {
        // gh CLI not available or not authenticated
    }

    // 4. If not required, return empty string (for public repos that don't need code search)
    if (!requireToken) {
        return '';
    }

    // 5. No token found but required - prompt user
    console.log(chalk.yellow('\n⚠️  No GitHub token found.\n'));
    console.log(chalk.dim('A GitHub token is required for the SEARCH_CODE feature.'));
    console.log(chalk.dim('You can set it via:'));
    console.log(chalk.dim('  • gh auth login (recommended - GitHub CLI)'));
    console.log(chalk.dim('  • --github-token <token> flag'));
    console.log(chalk.dim('  • GITHUB_TOKEN environment variable\n'));

    const answers = await inquirer.prompt([
        {
            type: 'password',
            name: 'githubToken',
            message: 'Enter your GitHub token:',
            mask: '•',
            validate: (input: string) => {
                if (!input || input.trim().length === 0) {
                    return 'GitHub token is required for code search';
                }
                return true;
            },
        },
    ]);

    return answers.githubToken;
}
