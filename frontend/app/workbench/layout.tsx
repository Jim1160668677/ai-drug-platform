import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';
import ScientistCopilot from '@/components/coscientist/ScientistCopilot';

export default function WorkbenchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto bg-gray-50 p-6">{children}</main>
      </div>
      {/* 伴随式科学推理助手（全局浮窗，嵌入工作流） */}
      <ScientistCopilot />
    </div>
  );
}
