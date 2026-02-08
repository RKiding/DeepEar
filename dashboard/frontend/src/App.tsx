import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { Login } from './components/auth/Login'
import { Register } from './components/auth/Register'
import { ProtectedRoute } from './components/ProtectedRoute'
import { Dashboard } from './Dashboard'
import { LiteDashboard } from './LiteDashboard'
import { LiteChartPage } from './LiteChartPage'
import './App.css'

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/lite" element={<LiteDashboard />} />
        <Route path="/lite/chart/:ticker" element={<LiteChartPage />} />

        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Dashboard />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  )
}

export default App
