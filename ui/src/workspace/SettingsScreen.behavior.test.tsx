// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi, type Mock } from 'vitest';
import type { JarvisClient } from '../backend';
import type { SettingRow, SettingsView, SettingsPatchResult } from '../types';
import { SettingsScreen } from './SettingsScreen';

vi.mock('../backend', () => ({ isTauri: () => false, loadBootstrap: () => Promise.reject(new Error('시험에서는 연결 설정을 불러오지 않음')) }));
let root: Root;
let container: HTMLDivElement;
let view: SettingsView;
let client: JarvisClient;
let close: Mock<() => void>;
const row = (key: string, kind: SettingRow['kind'], value: SettingRow['value'], group = 'general'): SettingRow =>
  ({key, group, label: key, kind, value, help: '', choices: [], min: null, max: null, lab: false, source: 'default', live: true, restart_required: false});

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  close = vi.fn<() => void>();
  view = {groups: [{id:'general',label:'일반'}, {id:'permissions',label:'권한·안전'}], path:'시험',
    settings: [row('user_label','str','이전호칭'), row('ollama_max_tool_steps','int',12), row('google_write_enabled','bool',false,'permissions')]};
  client = {
    getSettings: vi.fn(async () => structuredClone(view)),
    patchSettings: vi.fn(async (values) => {
      view.settings = view.settings.map(r => r.key in values ? {...r,value:values[r.key],source:'user'} : r);
      return {ok:true,applied:Object.keys(values),restart_required:[],...structuredClone(view)};
    }),
    resetSettings: vi.fn(async () => ({ok:true,applied:[],restart_required:[],...structuredClone(view)})),
    startGoogleOAuth: vi.fn(async () => ({ok:true,opened_browser:true,authorization_url:'시험'})),
    getGrantedPaths: vi.fn(async () => ({read:['C:/자료'],write:['D:/결과']})),
    revokeGrantedPath: vi.fn(async () => ({ok:true,granted_paths:{read:[],write:['D:/결과']}})),
  } as unknown as JarvisClient;
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.clearAllMocks(); });
async function render(open = true, section = 'general') {
  await act(async () => root.render(<SettingsScreen client={client} open={open} onClose={() => close()} initialSection={section} />));
}
const input = (key: string) => container.querySelector<HTMLInputElement>(`#setting-${key}`)!;
async function edit(key: string, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input(key), value);
    input(key).dispatchEvent(new Event('input',{bubbles:true}));
  });
}
async function blur(key: string) { await act(async () => input(key).dispatchEvent(new FocusEvent('focusout',{bubbles:true}))); }
async function click(button: Element) { await act(async () => (button as HTMLButtonElement).click()); }
async function enter(key: string) { await act(async () => input(key).dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))); }

it('글자칸은 저장 버튼으로 저장하고 해당 칸 아래에 결과를 표시한다', async () => {
  await render(); await edit('user_label','새호칭');
  const li = input('user_label').closest('li')!;
  const button = [...li.querySelectorAll('button')].find(b => b.textContent === '저장');
  expect(button).toBeDefined(); await click(button!);
  expect(client.patchSettings).toHaveBeenCalledWith({user_label:'새호칭'});
  expect(li.textContent).toContain('저장됨');
});

it('ESC는 저장이 끝난 뒤에만 닫는다', async () => {
  await render(); await edit('user_label','ESC호칭');
  let finish!: (v: SettingsPatchResult) => void;
  vi.mocked(client.patchSettings).mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}) as ReturnType<JarvisClient['patchSettings']>);
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})));
  expect(client.patchSettings).toHaveBeenCalledWith({user_label:'ESC호칭'}); expect(close).not.toHaveBeenCalled();
  await act(async () => finish({ok:true,applied:['user_label'],restart_required:[],...view}));
  expect(close).toHaveBeenCalledOnce();
});

it('저장 실패는 입력을 승인된 값으로 돌리고 해당 칸에 한국어 오류를 표시한다', async () => {
  await render(); vi.mocked(client.patchSettings).mockRejectedValueOnce(new Error('Failed to fetch'));
  await edit('user_label','거절된호칭'); await enter('user_label');
  expect(input('user_label').value).toBe('이전호칭');
  expect(input('user_label').closest('li')!.textContent).toContain('연결');
  expect(input('user_label').closest('li')!.textContent).not.toContain('Failed to fetch');
});

it('비어 있는 숫자는 0이나 null로 저장하지 않는다', async () => {
  await render(); await edit('ollama_max_tool_steps',''); await enter('ollama_max_tool_steps'); await blur('ollama_max_tool_steps');
  expect(client.patchSettings).not.toHaveBeenCalled();
  expect(input('ollama_max_tool_steps').closest('li')!.textContent).toContain('숫자');
});

it('읽기 실패 뒤 다시 열면 옛 오류를 지우고 새 설정을 읽는다', async () => {
  vi.mocked(client.getSettings).mockRejectedValueOnce(new Error('Failed to fetch')); await render();
  expect(container.textContent).not.toContain('Failed to fetch');
  await render(false); await render(); expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(input('user_label').value).toBe('이전호칭');
});

it('이 판에서 못 쓰는 목록 칸도 입력을 막는다', async () => {
  view.settings.push({...row('local_file_allowed_roots','list',['C:/시험']),unavailable:'이번 판에서는 못 씁니다'});
  await render(); expect(container.querySelector<HTMLTextAreaElement>('#setting-local_file_allowed_roots')!.disabled).toBe(true);
});

it('Google 쓰기를 켜면 저장 뒤 사람의 권한 연결을 시작한다', async () => {
  await render(true,'permissions'); await click(container.querySelector('[role="switch"]')!);
  expect(client.patchSettings).toHaveBeenCalledWith({google_write_enabled:true});
  expect(client.startGoogleOAuth).toHaveBeenCalledOnce();
});

it('권한 화면에서 승인된 폴더를 유형별로 보고 읽기 승인만 지운다', async () => {
  await render(true, 'permissions');
  expect(container.textContent).toContain('C:/자료');
  expect(container.textContent).toContain('D:/결과');
  await click(container.querySelector('[aria-label="읽기 승인 지우기: C:/자료"]')!);
  expect(client.revokeGrantedPath).toHaveBeenCalledWith('C:/자료', 'read');
  expect(container.textContent).not.toContain('C:/자료');
  expect(container.textContent).toContain('D:/결과');
});

it('Google 권한 연결 실패를 설정 저장 실패로 표시하지 않는다', async () => {
  vi.mocked(client.startGoogleOAuth).mockRejectedValueOnce(new Error('Failed to fetch'));
  await render(true,'permissions'); await click(container.querySelector('[role="switch"]')!);
  expect(container.querySelector('[role="switch"]')!.getAttribute('aria-checked')).toBe('true');
  expect(container.textContent).toContain('설정은 저장'); expect(container.textContent).toContain('권한 연결');
});

it('다른 칸을 저장해도 아직 저장하지 않은 글자 초안은 남는다', async () => {
  await render(); await edit('user_label','남아야할초안'); await edit('ollama_max_tool_steps','14'); await enter('ollama_max_tool_steps');
  expect(input('user_label').value).toBe('남아야할초안');
});

it('두 칸 저장은 순서대로 진행하고 기다리는 칸의 표시를 먼저 지우지 않는다', async () => {
  await render(); let finish!: (v: SettingsPatchResult) => void;
  vi.mocked(client.patchSettings).mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}) as ReturnType<JarvisClient['patchSettings']>);
  await edit('user_label','호칭'); await enter('user_label'); await edit('ollama_max_tool_steps','15'); await enter('ollama_max_tool_steps');
  expect(client.patchSettings).toHaveBeenCalledTimes(1);
  expect(input('user_label').disabled).toBe(true); expect(input('ollama_max_tool_steps').disabled).toBe(true);
  await act(async () => finish({ok:true,applied:['user_label'],restart_required:[],...view}));
  expect(client.patchSettings).toHaveBeenCalledTimes(2); expect(input('ollama_max_tool_steps').value).toBe('15');
});

it('ESC 저장이 실패하면 설정을 닫지 않는다', async () => {
  await render(); await edit('user_label','거절'); vi.mocked(client.patchSettings).mockRejectedValueOnce(new Error('Failed to fetch'));
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})));
  expect(close).not.toHaveBeenCalled(); expect(input('user_label').closest('li')!.textContent).toContain('연결');
});

it('기본값 복원 실패도 한국어로 해당 칸에서 알린다', async () => {
  view.settings[0].source = 'user'; await render(); vi.mocked(client.resetSettings).mockRejectedValueOnce(new Error('Failed to fetch'));
  await click(input('user_label').closest('li')!.querySelector('button')!);
  expect(input('user_label').closest('li')!.textContent).toContain('연결'); expect(container.textContent).not.toContain('Failed to fetch');
});
