// @ts-nocheck: Node test runner; excluded from app type semantics.
/**
 * Runtime-status unit tests (Node built-in test runner + tsx).
 * Run: npx tsx --test src/lib/tests/runtime-status.test.ts
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  MOCK_COMPONENT_MATRIX,
  MOCK_RUNTIME_STATUSES,
  PROVIDER_INACTIVITY_FRAGMENT,
  aiNoticePresentation,
  allowsComponentInstall,
  classifyAiNotice,
  componentStateLabel,
  isImmutableFull,
  legacyRuntimeStatusFromProvision,
  lifecycleLabel,
  mockLiteRepairableAfterFailedStaging,
  showsRepairAction,
} from '../runtime-status';

describe('runtime status mocks cover every lifecycle', () => {
  const lifecycles = new Set(MOCK_RUNTIME_STATUSES.map(s => s.status));
  const editions = new Set(MOCK_RUNTIME_STATUSES.map(s => s.edition));

  it('includes all runtime lifecycle values', () => {
    for (const expected of ['missing', 'installing', 'ready', 'invalid', 'repairable'] as const) {
      assert.ok(lifecycles.has(expected), `missing mock for lifecycle ${expected}`);
    }
  });

  it('includes lite and full editions', () => {
    assert.ok(editions.has('lite'));
    assert.ok(editions.has('full'));
  });

  it('labels every component state', () => {
    for (const row of MOCK_COMPONENT_MATRIX) {
      for (const state of Object.values(row)) {
        assert.ok(componentStateLabel(state).length > 0);
      }
    }
  });
});

describe('Full edition install policy', () => {
  const fullReady = MOCK_RUNTIME_STATUSES.find(s => s.edition === 'full' && s.status === 'ready')!;

  it('treats Full as immutable', () => {
    assert.equal(isImmutableFull(fullReady), true);
    assert.equal(allowsComponentInstall(fullReady), false);
  });

  it('allows Lite ready installs', () => {
    const liteReady = MOCK_RUNTIME_STATUSES.find(s => s.edition === 'lite' && s.status === 'ready')!;
    assert.equal(allowsComponentInstall(liteReady), true);
  });
});

describe('Lite repair after failed staging', () => {
  const repairable = mockLiteRepairableAfterFailedStaging();

  it('keeps core installed and exposes repair', () => {
    assert.equal(repairable.components.core, 'installed');
    assert.equal(repairable.components.ocr, 'failed');
    assert.equal(repairable.status, 'repairable');
    assert.equal(showsRepairAction(repairable), true);
    assert.equal(repairable.repair_action, 'repair_component');
  });

  it('legacy adapter maps not_provisioned to missing', () => {
    const status = legacyRuntimeStatusFromProvision({ state: 'not_provisioned' });
    assert.equal(status.status, 'missing');
    assert.equal(status.edition, 'lite');
    assert.equal(lifecycleLabel(status.status), 'Not provisioned');
  });
});

describe('AI notice classification', () => {
  it('distinguishes cancellation from inactivity', () => {
    const cancelled = classifyAiNotice('AI cleanup cancelled — kept the original text.');
    const inactive = classifyAiNotice(
      `AI cleanup stopped because The ${PROVIDER_INACTIVITY_FRAGMENT} for 180 seconds. Kept the original text.`,
    );
    assert.equal(cancelled, 'cancelled');
    assert.equal(inactive, 'inactivity');
    assert.notEqual(cancelled, inactive);
  });

  it('distinguishes provider failure from inactivity', () => {
    const provider = classifyAiNotice('AI cleanup unavailable: HTTP 503 — kept the original text.');
    const inactive = classifyAiNotice(`AI cleanup stopped because The ${PROVIDER_INACTIVITY_FRAGMENT} for 30 seconds. Kept the original text.`);
    assert.equal(provider, 'provider');
    assert.equal(inactive, 'inactivity');
  });

  it('maps presentation classes', () => {
    assert.equal(aiNoticePresentation('cancelled').className, 'notice-cancelled');
    assert.equal(aiNoticePresentation('inactivity').prefix, 'Provider inactive');
    assert.equal(aiNoticePresentation('provider').prefix, 'Provider error');
  });
});
