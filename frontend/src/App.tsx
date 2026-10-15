import { NavLink, Route, Routes } from "react-router-dom";
import { HongKongFlag } from "./components/HongKongFlag";
import { DialogueLibraryPage } from "./pages/DialogueLibraryPage";
import { ExtractedDocPage } from "./pages/ExtractedDocPage";
import { ImportPage } from "./pages/ImportPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { VocabDashboardPage } from "./pages/VocabDashboardPage";

function Nav() {
  return (
    <nav className="top-nav">
      <HongKongFlag />
      <NavLink to="/" end>
        Library
      </NavLink>
      <NavLink to="/import">Import</NavLink>
      <NavLink to="/vocab">Vocab</NavLink>
      <NavLink to="/settings">Settings</NavLink>
    </nav>
  );
}

export function App() {
  return (
    <div>
      <Nav />
      <Routes>
        <Route path="/" element={<DialogueLibraryPage />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="/vocab" element={<VocabDashboardPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/dialogues/:dialogueId/review" element={<ReviewPage />} />
        <Route path="/dialogues/:dialogueId/doc" element={<ExtractedDocPage />} />
      </Routes>
    </div>
  );
}
