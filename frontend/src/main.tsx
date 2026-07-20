import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import './index.css'
import App from './App'
import EditorPage from './pages/EditorPage'
import FramePickerPage from './pages/FramePickerPage'
import HomePage from './pages/HomePage'
import JobsPage from './pages/JobsPage'
import UploadPage from './pages/UploadPage'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'upload', element: <UploadPage /> },
      { path: 'frame/:videoId', element: <FramePickerPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: 'edit/:jobId', element: <EditorPage /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
