import type { Plugin } from 'vite';
export function buildEntries(here: string): { outDir: string; input: Record<string, string> };
export function characterAssets(here: string, headers: Record<string, string>): Plugin;
