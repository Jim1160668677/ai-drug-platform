import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type {
  AgentSession,
  AgentMessage,
  ToolCall,
  ToolResult,
} from '@/types/agent';

interface ProjectInfo {
  id: string;
  name: string;
  cancer_type?: string;
  stage?: string;
  status?: string;
}

/** Agent 工作台状态切片 */
interface AgentSlice {
  agentSessions: AgentSession[];
  currentSessionId: string | null;
  currentTaskId: string | null;
  messages: AgentMessage[];
  pendingConfirmation: {
    task_id: string;
    tool: string;
    args: Record<string, unknown>;
  } | null;
  isAgentLoading: boolean;
  latestToolResult: ToolResult | null;
  // 流式 token 累积（用于 LLM 流式响应实时显示）
  streamingMessageId: string | null;
  setAgentSessions: (sessions: AgentSession[]) => void;
  setCurrentSession: (id: string | null) => void;
  setCurrentTaskId: (id: string | null) => void;
  appendMessage: (msg: AgentMessage) => void;
  appendToolCall: (taskId: string, call: ToolCall) => void;
  appendToolResult: (taskId: string, result: ToolResult) => void;
  setPendingConfirmation: (
    c: { task_id: string; tool: string; args: Record<string, unknown> } | null
  ) => void;
  setAgentLoading: (b: boolean) => void;
  appendStreamingToken: (token: string, step?: number) => void;
  clearStreamingMessage: () => void;
  resetAgent: () => void;
}

/** 个人基因组解读切片 */
interface GenomeSlice {
  selectedGenomeId: string | null;
  selectedTraitId: string | null;
  setSelectedGenome: (id: string | null) => void;
  setSelectedTrait: (id: string | null) => void;
}

interface AppState extends AgentSlice, GenomeSlice {
  user: {
    role: string; // 职级：founder/chief/researcher/doctor/engineer
    name: string;
    email: string;
    // 新增职能维度（nullable，向后兼容旧用户）
    function_role?: string; // target_discovery/molecule_design/clinical_guidance/...
    org_id?: string;
    org_name?: string;
    title?: string;
  } | null;
  currentProject: ProjectInfo | null;
  sidebarCollapsed: boolean;
  // Co-Scientist 伴随式助手（全局浮窗）开关
  copilotOpen: boolean;
  setCopilotOpen: (open: boolean) => void;
  setUser: (user: AppState['user']) => void;
  clearUser: () => void;
  setProject: (project: ProjectInfo | null) => void;
  toggleSidebar: () => void;
}

const initialAgentState = {
  agentSessions: [] as AgentSession[],
  currentSessionId: null as string | null,
  currentTaskId: null as string | null,
  messages: [] as AgentMessage[],
  pendingConfirmation: null as AgentSlice['pendingConfirmation'],
  isAgentLoading: false,
  latestToolResult: null as ToolResult | null,
  streamingMessageId: null as string | null,
};

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      user: null,
      currentProject: null,
      sidebarCollapsed: false,
      copilotOpen: false,
      ...initialAgentState,

      // ===== 个人基因组切片 =====
      selectedGenomeId: null,
      selectedTraitId: null,
      setSelectedGenome: (id) => set({ selectedGenomeId: id }),
      setSelectedTrait: (id) => set({ selectedTraitId: id }),

      setCopilotOpen: (open) => set({ copilotOpen: open }),
      setUser: (user) => set({ user }),
      clearUser: () => set({ user: null }),
      setProject: (project) => set({ currentProject: project }),
      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

      // ===== Agent 切片 =====
      setAgentSessions: (sessions) => set({ agentSessions: sessions }),
      setCurrentSession: (id) =>
        set({ currentSessionId: id, messages: [], currentTaskId: null, latestToolResult: null }),
      setCurrentTaskId: (id) => set({ currentTaskId: id }),
      appendMessage: (msg) =>
        set((state) => ({ messages: [...state.messages, msg] })),
      appendToolCall: (taskId, call) =>
        set((state) => {
          // 找到最后一条 assistant 消息，把 toolCall 追加进去
          const msgs = [...state.messages];
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'assistant') {
              msgs[i] = {
                ...msgs[i],
                toolCalls: [...(msgs[i].toolCalls ?? []), call],
              };
              break;
            }
          }
          // 若没有 assistant 消息，则新建一条
          if (!msgs.some((m) => m.role === 'assistant' && m.toolCalls?.length)) {
            msgs.push({
              id: `msg-${Date.now()}-tool-${call.step}`,
              role: 'assistant',
              content: call.thought ?? '',
              toolCalls: [call],
              step: call.step,
              timestamp: new Date().toISOString(),
            });
          }
          return { messages: msgs, currentTaskId: taskId };
        }),
      appendToolResult: (taskId, result) =>
        set((state) => {
          const msgs = [...state.messages];
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'assistant') {
              msgs[i] = {
                ...msgs[i],
                toolResults: [...(msgs[i].toolResults ?? []), result],
              };
              break;
            }
          }
          return { messages: msgs, latestToolResult: result };
        }),
      setPendingConfirmation: (c) => set({ pendingConfirmation: c }),
      setAgentLoading: (b) => set({ isAgentLoading: b }),
      // ========== 流式 token 累积 ==========
      // 用于 LLM 流式响应实时显示：每次 token 到达时追加到 streaming 消息，
      // 在 thought/tool_call/final_response 等结构化事件到达时清理。
      appendStreamingToken: (token, step) =>
        set((state) => {
          const msgs = [...state.messages];
          let { streamingMessageId } = state;
          // 若不存在 streaming 消息，新建一条
          if (!streamingMessageId || !msgs.some((m) => m.id === streamingMessageId)) {
            streamingMessageId = `msg-${Date.now()}-stream`;
            msgs.push({
              id: streamingMessageId,
              role: 'assistant',
              content: token,
              timestamp: new Date().toISOString(),
              isStreaming: true,
              step,
            });
          } else {
            // 已存在 streaming 消息，追加 token
            const idx = msgs.findIndex((m) => m.id === streamingMessageId);
            if (idx >= 0) {
              msgs[idx] = {
                ...msgs[idx],
                content: msgs[idx].content + token,
              };
            }
          }
          return { messages: msgs, streamingMessageId };
        }),
      clearStreamingMessage: () =>
        set((state) => {
          if (!state.streamingMessageId) return state;
          // 移除 streaming 消息（已由 thought/tool_call/final_response 等结构化事件取代）
          const msgs = state.messages.filter(
            (m) => m.id !== state.streamingMessageId
          );
          return { messages: msgs, streamingMessageId: null };
        }),
      resetAgent: () => set({ ...initialAgentState }),
    }),
    {
      name: 'ai-drug-store',
      skipHydration: true,
      // 仅持久化 user / currentProject / sidebarCollapsed，agent 状态不持久化
      partialize: (state) => ({
        user: state.user,
        currentProject: state.currentProject,
        sidebarCollapsed: state.sidebarCollapsed,
      }),
    }
  )
);
