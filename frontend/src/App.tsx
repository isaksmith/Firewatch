import { Route, Routes } from 'react-router-dom'
import { Dashboard } from './pages/Dashboard'
import { Spread3D } from './pages/Spread3D'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/alerts/:id" element={<Dashboard />} />
      <Route path="/alerts/:id/3d" element={<Spread3D />} />
    </Routes>
  )
}
