import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ProjectInfo {
  id: string;
  name: string;
  cancer_type?: string;
  stage?: string;
  status?: string;
}

interface AppState {
  user: { role: string; name: string; email: string } | null;
  currentProject: ProjectInfo | null;
  sidebarCollapsed: boolean;
  setUser: (user: { role: string; name: string; email: string } | null) => void;
  clearUser: () => void;
  setProject: (project: ProjectInfo | null) => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      user: null,
      currentProject: null,
      sidebarCollapsed: false,
      setUser: (user) => set({ user }),
      clearUser: () => set({ user: null }),
      setProject: (project) => set({ currentProject: project }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
    }),
    {
      name: 'ai-drug-store',
    }
  )
);
