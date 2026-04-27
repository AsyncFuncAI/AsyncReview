/**
 * Python environment setup and runner
 */

import { spawn, spawnSync } from 'child_process';
import chalk from 'chalk';
import ora from 'ora';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// From dist/ we need to go up to npx/ (or app/ in bundled mode)
const NPX_ROOT = path.resolve(__dirname, '..');

// Bundled mode detection: In runtime cache, there's a `pydeps/` sibling to `app/`
const PYDEPS_DIR = path.resolve(NPX_ROOT, '..', 'pydeps');
const IS_BUNDLED = fs.existsSync(PYDEPS_DIR);

// Python code always lives in npx/python/ (or app/python/ in bundled mode)
const PYTHON_CODE_ROOT = path.resolve(NPX_ROOT, 'python');

// Build PYTHONPATH: include pydeps if bundled, otherwise just the code root
function getPythonPath(): string {
    if (IS_BUNDLED) {
        return `${PYDEPS_DIR}:${PYTHON_CODE_ROOT}`;
    }
    return process.env.PYTHONPATH
        ? `${PYTHON_CODE_ROOT}:${process.env.PYTHONPATH}`
        : PYTHON_CODE_ROOT;
}

interface PythonCheckResult {
    available: boolean;
    version?: string;
    pythonCmd: string;
}

interface DenoCheckResult {
    available: boolean;
    version?: string;
}

/**
 * Check if Python 3.11+ is available
 * Prioritizes virtual environment Python if it exists
 */
export function checkPython(): PythonCheckResult {
    // Check for local venv Python first (in npx/.venv)
    const localVenvPython = path.join(NPX_ROOT, '.venv', 'bin', 'python');

    // Check if the local venv python exists and is executable
    try {
        if (spawnSync('test', ['-x', localVenvPython]).status === 0) {
            const result = spawnSync(localVenvPython, ['--version'], { encoding: 'utf-8' });
            if (result.status === 0) {
                return { available: true, version: result.stdout.trim(), pythonCmd: localVenvPython };
            }
        }
    } catch { }

    // Fallback to system python to bootstrap
    for (const cmd of ['python3', 'python']) {
        try {
            const result = spawnSync(cmd, ['--version'], { encoding: 'utf-8' });
            if (result.status === 0) {
                const version = result.stdout.trim() || result.stderr.trim();
                const match = version.match(/Python (\d+)\.(\d+)/);
                if (match) {
                    const major = parseInt(match[1]);
                    const minor = parseInt(match[2]);
                    if (major >= 3 && minor >= 11) {
                        return { available: true, version, pythonCmd: cmd };
                    }
                }
            }
        } catch {
            // Continue to next command
        }
    }
    return { available: false, pythonCmd: 'python3' };
}

/**
 * Check if Deno is installed
 */
export function checkDeno(): DenoCheckResult {
    try {
        const result = spawnSync('deno', ['--version'], { encoding: 'utf-8' });
        if (result.status === 0) {
            // Extract version from output (first line contains "deno x.x.x")
            const version = result.stdout.split('\n')[0].trim();
            return { available: true, version };
        }
    } catch {
        // Deno not found
    }
    return { available: false };
}

/**
 * Install Deno using the official installation script
 */
export async function installDeno(quiet: boolean = false): Promise<boolean> {
    const ora = (await import('ora')).default;
    const spinner = !quiet ? ora('Installing Deno...').start() : null;

    try {
        return new Promise((resolve) => {
            // Run the official Deno install script
            const proc = spawn('sh', ['-c', 'curl -fsSL https://deno.land/install.sh | sh'], {
                stdio: ['ignore', 'pipe', 'pipe'],
                env: {
                    ...process.env,
                }
            });

            let stderr = '';
            proc.stderr.on('data', (data) => {
                stderr += data.toString();
            });

            proc.on('close', (code) => {
                if (code === 0) {
                    // Add Deno to PATH for this session
                    const homeDir = process.env.HOME || process.env.USERPROFILE || '';
                    const denoBinPath = path.join(homeDir, '.deno', 'bin');
                    process.env.PATH = `${denoBinPath}:${process.env.PATH}`;

                    if (spinner) spinner.succeed('Deno installed successfully');
                    if (!quiet) {
                        console.log(chalk.dim('\nNote: Add the following to your shell profile (~/.bashrc, ~/.zshrc, etc.):'));
                        console.log(chalk.yellow(`  export PATH="${denoBinPath}:$PATH"`));
                    }
                    resolve(true);
                } else {
                    if (spinner) spinner.fail('Failed to install Deno');
                    if (!quiet) {
                        console.error(chalk.red('\nDeno installation failed:'));
                        console.error(stderr);
                    }
                    resolve(false);
                }
            });

            proc.on('error', (err) => {
                if (spinner) spinner.fail('Failed to start Deno installation');
                if (!quiet) {
                    console.error(chalk.red('\nError:'), err.message);
                }
                resolve(false);
            });
        });
    } catch (e) {
        if (spinner) spinner.fail('Failed to install Deno');
        return false;
    }
}

/**
 * Check if asyncreview Python package is installed
 */
export function checkAsyncReviewInstalled(pythonCmd: string): boolean {
    try {
        // Check for both cli module and rich (as a proxy for dependencies)
        const result = spawnSync(pythonCmd, ['-c', 'import cli.main; import rich; import dspy'], {
            encoding: 'utf-8',
            cwd: PYTHON_CODE_ROOT,
            env: {
                ...process.env,
                PYTHONPATH: getPythonPath(),
            }
        });
        return result.status === 0;
    } catch {
        return false;
    }
}

/**
 * Setup virtual environment and install dependencies
 */
/**
 * Setup virtual environment and install dependencies
 */
export async function installAsyncReview(systemPython: string, quiet: boolean = false): Promise<boolean> {
    const spinner = !quiet ? ora('Setting up isolated Python environment...').start() : null;
    // Venv always lives in npx/.venv, regardless of bundled vs dev mode
    const venvDir = path.join(NPX_ROOT, '.venv');

    try {
        // 1. Create venv if it doesn't exist
        if (spinner) spinner.text = 'Creating virtual environment...';
        spawnSync(systemPython, ['-m', 'venv', venvDir]);

        const venvPip = path.join(venvDir, 'bin', 'pip');

        // 2. Install dependencies via pip
        if (spinner) spinner.text = 'Installing dependencies (this may take a minute)...';

        return new Promise((resolve) => {
            // Install from the Python code directory
            const args = ['install', '.'];

            const proc = spawn(venvPip, args, {
                cwd: PYTHON_CODE_ROOT,
                stdio: ['ignore', 'pipe', 'pipe']
            });

            let stdout = '';
            let stderr = '';

            proc.stdout.on('data', (data) => {
                stdout += data.toString();
            });

            proc.stderr.on('data', (data) => {
                stderr += data.toString();
            });

            proc.on('close', (code) => {
                if (code === 0) {
                    if (spinner) spinner.succeed('AsyncReview environment ready');
                    resolve(true);
                } else {
                    if (spinner) spinner.fail('Failed to install dependencies');
                    if (!quiet) {
                        console.error(chalk.red('\nPip installation error:'));
                        console.error(stderr || stdout);
                    }
                    resolve(false);
                }
            });

            proc.on('error', (err) => {
                if (spinner) spinner.fail('Failed to start installation');
                if (!quiet) {
                    console.error(chalk.red('\nError spawning pip:'));
                    console.error(err.message);
                    console.error(chalk.dim(`Attempted to run: ${venvPip} ${args.join(' ')}`));
                    console.error(chalk.dim(`CWD: ${PYTHON_CODE_ROOT}`));
                }
                resolve(false);
            });
        });

    } catch (e) {
        if (spinner) spinner.fail('Failed to setup environment');
        return false;
    }
}

export interface RunOptions {
    url?: string;
    path?: string;
    question?: string;
    output: string;
    quiet: boolean;
    model?: string;
    apiKey: string;
    githubToken?: string;
    expert?: boolean;
}

/**
 * Run the Python asyncreview CLI using the isolated environment
 */
export async function runPythonReview(options: RunOptions): Promise<string> {

    // 1. Ensure we have a valid environment
    let pythonCheck = checkPython();

    // If we don't have a venv python, or we have one but dependencies aren't there
    // We need to trigger installation using the system python we found
    if (!pythonCheck.available) throw new Error("Python 3.11+ required to set up environment");

    const venvPython = path.join(NPX_ROOT, '.venv', 'bin', 'python');

    // Force usage of venv python for execution
    const pythonCmd = checkAsyncReviewInstalled(venvPython) ? venvPython : pythonCheck.pythonCmd;

    return new Promise((resolve, reject) => {
        const args = [
            '-m', 'cli.main',
            'review',
        ];

        // Add either --url or --path (mutually exclusive)
        if (options.url) {
            args.push('--url', options.url);
        } else if (options.path) {
            args.push('--path', options.path);
        }

        args.push('--output', options.output);

        // Add question if provided
        if (options.question) {
            args.push('-q', options.question);
        }

        // Add expert flag if enabled
        if (options.expert) {
            args.push('--expert');
        }

        if (options.quiet) {
            args.push('--quiet');
        }

        if (options.model) {
            args.push('--model', options.model);
        }

        // Use centralized PYTHONPATH (handles bundled vs dev mode)
        const pythonPath = getPythonPath();

        const proc = spawn(pythonCmd, args, {
            cwd: PYTHON_CODE_ROOT,
            env: {
                ...process.env,
                GEMINI_API_KEY: options.apiKey,
                ...(options.githubToken && { GITHUB_TOKEN: options.githubToken }),
                PYTHONPATH: pythonPath,
                // Ensure we don't inherit conflicting python env vars
                VIRTUAL_ENV: path.dirname(path.dirname(pythonCmd))
            },
            stdio: ['pipe', 'pipe', 'pipe'],
        });

        let stdout = '';
        let stderr = '';

        proc.stdout.on('data', (data) => {
            stdout += data.toString();
            if (!options.quiet) {
                process.stdout.write(data);
            }
        });

        proc.stderr.on('data', (data) => {
            stderr += data.toString();
            if (!options.quiet) {
                process.stderr.write(data);
            }
        });

        proc.on('close', (code) => {
            if (code === 0) {
                resolve(stdout);
            } else {
                reject(new Error(stderr || `Process exited with code ${code}`));
            }
        });

        proc.on('error', (err) => {
            reject(err);
        });
    });
}
