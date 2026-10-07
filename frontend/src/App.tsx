import { useState } from "react";
import { Header, type Screen } from "./components/Header";
import { Toasts } from "./components/Toasts";
import { Assistant } from "./screens/Assistant";
import { Memory } from "./screens/Memory";
import { Routines } from "./screens/Routines";
import { Evidence } from "./screens/Evidence";

export function App() {
  const [screen, setScreen] = useState<Screen>("assistant");
  return (
    <div className="flex h-full flex-col bg-surface text-ink">
      <Header screen={screen} onNavigate={setScreen} />
      <main className="min-h-0 flex-1">
        {screen === "assistant" && <Assistant />}
        {screen === "memory" && <Memory />}
        {screen === "routines" && <Routines />}
        {screen === "evidence" && <Evidence />}
      </main>
      <Toasts />
    </div>
  );
}
