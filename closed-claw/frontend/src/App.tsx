import LeftSidebar from './components/Layout/LeftSidebar';
import RightChatDrawer from './components/Layout/RightChatDrawer';
import FleetMonitor from './components/Viewports/FleetMonitor';
import BacktestView from './components/Viewports/BacktestView';
import VMViewer from './components/Viewports/VMViewer';
import { useAgentStore } from './stores/useAgentStore';

export default function App() {
  const view = useAgentStore((s) => s.view);
  return (
    <div className="shell">
      <LeftSidebar />
      <main className="main">
        {view === 'fleet' && <FleetMonitor />}
        {view === 'backtest' && <BacktestView />}
        {view === 'vm' && <VMViewer />}
      </main>
      <RightChatDrawer />
    </div>
  );
}
