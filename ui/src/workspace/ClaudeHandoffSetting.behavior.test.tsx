// @vitest-environment jsdom
/**
 * 설정 › 연결의 「막히면 내 클로드에게 넘기기」(2026-10-19).
 *
 * - 이음 카드(「클로드·코덱스·커서에서 Sonjari 쓰기」) 뒤에 반대 방향 스위치로 그린다 — 다른 설정 칸과 같은 부품.
 * - 기본 꺼짐. 누르면 그 한 칸만 저장한다.
 * - 클로드 명령 · 로그인이 없거나 관리자가 꺼 뒀으면 눌리지 않고, 짧은 상태 말과 까닭을 보인다(켜짐으로 그리지 않는다).
 * - 서버가 거절하면(그 사이 로그아웃 등) 코드 대신 사람 말로.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { JarvisClient } from '../backend';
import type { SettingRow, SettingsView } from '../types';
import { SettingsScreen } from './SettingsScreen';

vi.mock('../backend', () => ({ isTauri: () => false, loadBootstrap: () => Promise.reject(new Error('시험에서는 연결 설정을 불러오지 않음')) }));

let root: Root;
let container: HTMLDivElement;
let view: SettingsView;
let client: JarvisClient;

const handoff = (extra: Partial<SettingRow> = {}): SettingRow => ({
  key: 'claude_code_enabled', group: 'connect', label: '막히면 내 클로드에게 넘기기', kind: 'bool', value: false,
  help: '손자리가 코드 일에서 막혔을 때만 이 PC 의 Claude Code 에 넘깁니다. 내 Claude 구독의 사용 한도를 씁니다.',
  choices: [], min: null, max: null, lab: false, source: 'default', live: true, restart_required: false, unavailable: '',
  ...extra,
});

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  view = { groups: [{ id: 'general', label: '일반' }], path: '시험', settings: [handoff()] };
  client = {
    getSettings: vi.fn(async () => structuredClone(view)),
    patchSettings: vi.fn(async (values) => {
      view.settings = view.settings.map((r) => (r.key in values ? { ...r, value: values[r.key], source: 'user' } : r));
      return { ok: true, applied: Object.keys(values), restart_required: [], ...structuredClone(view) };
    }),
    resetSettings: vi.fn(async () => ({ ok: true, applied: [], restart_required: [], ...structuredClone(view) })),
    getSavings: vi.fn(async () => ({ host_word: 'claude', tokens_at_least: 0, basis: '', top: [],
      jobs: { total: 0, done: 0, stopped: 0, in_progress: 0 } })),
  } as unknown as JarvisClient;
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.clearAllMocks(); });

async function renderConnect() {
  await act(async () => root.render(<SettingsScreen client={client} open onClose={() => undefined} initialSection="connect" />));
}
const toggle = () => container.querySelector<HTMLButtonElement>('#setting-claude_code_enabled')!;

it('연결 화면의 이음 카드 뒤에 기본 꺼짐 스위치와 한 줄 설명을 그린다', async () => {
  await renderConnect();
  const text = container.textContent ?? '';
  expect(toggle().getAttribute('role')).toBe('switch');
  expect(toggle().getAttribute('aria-checked')).toBe('false');
  expect(toggle().disabled).toBe(false);
  expect(text).toContain('막히면 내 클로드에게 넘기기');
  expect(text).toContain('구독의 사용 한도');
  // 이음 카드(클로드 → 손자리) 다음이 반대 방향(손자리 → 클로드)이다.
  expect(text.indexOf('클로드·코덱스·커서에서 Sonjari 쓰기')).toBeLessThan(text.indexOf('막히면 내 클로드에게 넘기기'));
  // 다른 화면(일반)에는 이 칸이 없다.
  await act(async () => [...container.querySelectorAll('button')].find((b) => b.textContent === '일반')!.click());
  expect(container.querySelector('#setting-claude_code_enabled')).toBeNull();
});

it('누르면 그 칸만 켜짐으로 저장하고 서버가 돌려준 값으로 다시 그린다', async () => {
  await renderConnect();
  await act(async () => toggle().click());
  expect(client.patchSettings).toHaveBeenCalledWith({ claude_code_enabled: true });
  expect(toggle().getAttribute('aria-checked')).toBe('true');
  expect(toggle().closest('li')!.textContent).toContain('저장됨');
});

it.each([
  ['Claude Code 없음', '이 PC 에 Claude Code(claude 명령)가 없습니다. 설치하고 로그인하면 켤 수 있습니다.'],
  ['로그인 필요', 'Claude Code 에 로그인하지 않았습니다. 명령 창에서 claude 를 한 번 실행해 로그인하면 켤 수 있습니다.'],
  ['관리자가 꺼 둠', '관리자가 이 PC 에서 꺼 두었습니다.'],
])('켤 수 없으면(%s) 눌리지 않고 까닭을 보인다 — 저장해 둔 켜짐도 켜짐으로 그리지 않는다', async (short, reason) => {
  view.settings = [handoff({ value: true, source: 'user', unavailable: reason, unavailable_short: short })];
  await renderConnect();
  expect(toggle().disabled).toBe(true);
  expect(toggle().getAttribute('aria-checked')).toBe('false');
  const li = toggle().closest('li')!;
  expect(li.textContent).toContain(short);
  expect(li.textContent).toContain(reason);
  expect(li.textContent).not.toContain('이 판에서는 못 씁니다');
  await act(async () => toggle().click());
  expect(client.patchSettings).not.toHaveBeenCalled();
});

it('서버가 켜기를 거절하면 코드 대신 사람 말로 알린다', async () => {
  vi.mocked(client.patchSettings).mockRejectedValueOnce(new Error('400 {"detail":"unavailable:claude_code_enabled"}'));
  await renderConnect();
  await act(async () => toggle().click());
  const li = toggle().closest('li')!;
  expect(li.textContent).toContain('지금은 켤 수 없습니다');
  expect(li.textContent).not.toContain('unavailable:');
});
