// Known API providers for AI cleanup. The dropdown writes api_type + api_base_url;
// Custom is the only row that still shows a Base URL field.

export type ApiKind = 'openai_compat' | 'anthropic';

export interface ApiProvider {
  id: string;
  label: string;
  apiType: ApiKind;
  /** Empty for Anthropic (fixed host) and for Custom (user-supplied). */
  baseUrl: string;
  /** Extra URLs that should still map back to this preset. */
  aliases?: string[];
  hint: string;
}

export const API_PROVIDERS: ApiProvider[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    apiType: 'openai_compat',
    baseUrl: 'https://api.openai.com/v1',
    hint: 'Keys start with sk- or sk-proj-',
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    apiType: 'openai_compat',
    baseUrl: 'https://api.deepseek.com',
    aliases: ['https://api.deepseek.com/v1'],
    hint: 'Keys start with sk-. Use api.deepseek.com, not openai.com.',
  },
  {
    id: 'groq',
    label: 'Groq',
    apiType: 'openai_compat',
    baseUrl: 'https://api.groq.com/openai/v1',
    hint: 'Keys start with gsk_',
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    apiType: 'anthropic',
    baseUrl: '',
    hint: 'Keys start with sk-ant-',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    apiType: 'openai_compat',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    aliases: ['https://generativelanguage.googleapis.com/v1beta/openai/'],
    hint: 'Google AI Studio keys start with AIza',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    apiType: 'openai_compat',
    baseUrl: 'https://openrouter.ai/api/v1',
    hint: 'Keys start with sk-or-',
  },
  {
    id: 'together',
    label: 'Together AI',
    apiType: 'openai_compat',
    baseUrl: 'https://api.together.xyz/v1',
    hint: 'OpenAI-compatible Together endpoint',
  },
  {
    id: 'mistral',
    label: 'Mistral',
    apiType: 'openai_compat',
    baseUrl: 'https://api.mistral.ai/v1',
    hint: 'La Plateforme keys',
  },
  {
    id: 'fireworks',
    label: 'Fireworks',
    apiType: 'openai_compat',
    baseUrl: 'https://api.fireworks.ai/inference/v1',
    hint: 'OpenAI-compatible Fireworks endpoint',
  },
  {
    id: 'xai',
    label: 'xAI (Grok)',
    apiType: 'openai_compat',
    baseUrl: 'https://api.x.ai/v1',
    hint: 'Keys start with xai-',
  },
  {
    id: 'perplexity',
    label: 'Perplexity',
    apiType: 'openai_compat',
    baseUrl: 'https://api.perplexity.ai',
    hint: 'Keys start with pplx-',
  },
  {
    id: 'cerebras',
    label: 'Cerebras',
    apiType: 'openai_compat',
    baseUrl: 'https://api.cerebras.ai/v1',
    hint: 'OpenAI-compatible Cerebras endpoint',
  },
  {
    id: 'nvidia',
    label: 'NVIDIA NIM',
    apiType: 'openai_compat',
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    hint: 'build.nvidia.com API keys',
  },
  {
    id: 'custom',
    label: 'Custom (OpenAI-compatible)',
    apiType: 'openai_compat',
    baseUrl: '',
    hint: 'Paste any OpenAI-compatible Base URL',
  },
];

export function providerById(id: string | undefined | null): ApiProvider {
  return API_PROVIDERS.find(p => p.id === id) ?? API_PROVIDERS[0];
}

function normUrl(url: string): string {
  return (url || '').trim().replace(/\/+$/, '').toLowerCase();
}

export function inferProviderId(apiType: string, baseUrl: string): string {
  if ((apiType || '') === 'anthropic') return 'anthropic';
  const u = normUrl(baseUrl);
  if (!u) return 'openai';
  for (const p of API_PROVIDERS) {
    if (p.id === 'custom' || p.id === 'anthropic') continue;
    const candidates = [p.baseUrl, ...(p.aliases ?? [])].map(normUrl).filter(Boolean);
    if (candidates.includes(u)) return p.id;
  }
  if (u.includes('openai.com')) return 'openai';
  return 'custom';
}

/** Unambiguous key prefixes only. Never guess between OpenAI and DeepSeek (both sk-). */
export function detectProviderFromKey(key: string): string | null {
  const k = (key || '').trim();
  if (k.startsWith('sk-ant-')) return 'anthropic';
  if (k.startsWith('gsk_')) return 'groq';
  if (k.startsWith('sk-or-')) return 'openrouter';
  if (k.startsWith('AIza')) return 'gemini';
  if (k.startsWith('xai-')) return 'xai';
  if (k.startsWith('pplx-')) return 'perplexity';
  return null;
}

export function providerLabel(id: string): string {
  return providerById(id).label;
}
