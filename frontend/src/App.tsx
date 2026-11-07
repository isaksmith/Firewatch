import { Route, Routes } from 'react-router-dom'
import { Dashboard } from './pages/Dashboard'
import { Planner } from './pages/Planner'
import { Spread3D } from './pages/Spread3D'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/alerts/:id" element={<Dashboard />} />
      <Route path="/alerts/:id/3d" element={<Spread3D />} />
      <Route path="/planner" element={<Planner />} />
    </Routes>
  )
}
