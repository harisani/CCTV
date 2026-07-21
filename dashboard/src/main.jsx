import React from 'react'
import { createRoot } from 'react-dom/client'
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material'
import App from './App'
import './styles/dashboard.css'

const theme = createTheme({
  typography: {
    fontFamily: 'var(--font-body)',
    h1: { fontFamily: 'var(--font-display)' },
    h2: { fontFamily: 'var(--font-display)' },
    h3: { fontFamily: 'var(--font-display)' },
    button: { fontFamily: 'var(--font-body)', textTransform: 'none' },
  },
  shape: { borderRadius: 6 },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { backgroundColor: 'var(--color-paper)', color: 'var(--color-ink-2)' },
      },
    },
  },
})

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  </React.StrictMode>,
)
