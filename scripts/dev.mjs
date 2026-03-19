/**
 * Dev coordinator script
 * - Finds available ports for backend and frontend
 * - Spawns both processes with correct environment variables
 * - Manages process lifecycle (kills both on exit)
 */

import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')

const DEFAULT_BACKEND_PORT = 5001
const DEFAULT_FRONTEND_PORT = 3000
const MAX_PORT_ATTEMPTS = 20

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = createServer()
    server.once('error', () => resolve(false))
    server.once('listening', () => {
      server.close(() => resolve(true))
    })
    server.listen(port, '0.0.0.0')
  })
}

async function findAvailablePort(startPort) {
  for (let i = 0; i < MAX_PORT_ATTEMPTS; i++) {
    const port = startPort + i
    if (await isPortAvailable(port)) return port
  }
  throw new Error(
    `No available port found in range ${startPort}-${startPort + MAX_PORT_ATTEMPTS - 1}`
  )
}

function colorize(text, color) {
  const colors = { green: '\x1b[32m', cyan: '\x1b[36m', yellow: '\x1b[33m', reset: '\x1b[0m' }
  return `${colors[color] || ''}${text}${colors.reset}`
}

async function main() {
  const backendPort = await findAvailablePort(DEFAULT_BACKEND_PORT)
  const frontendPort = await findAvailablePort(DEFAULT_FRONTEND_PORT)

  console.log('')
  console.log(colorize('  MiroFish Dev Server', 'cyan'))
  console.log(colorize(`  Backend:  http://localhost:${backendPort}`, 'green'))
  console.log(colorize(`  Frontend: http://localhost:${frontendPort}`, 'cyan'))
  if (backendPort !== DEFAULT_BACKEND_PORT || frontendPort !== DEFAULT_FRONTEND_PORT) {
    console.log(colorize('  (default ports were occupied, using alternatives)', 'yellow'))
  }
  console.log('')

  const children = []

  const backend = spawn('uv', ['run', 'python', 'run.py'], {
    cwd: resolve(ROOT, 'backend'),
    env: { ...process.env, FLASK_PORT: String(backendPort) },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  children.push(backend)

  backend.stdout.on('data', (data) => {
    process.stdout.write(colorize(`[backend]  `, 'green') + data.toString())
  })
  backend.stderr.on('data', (data) => {
    process.stderr.write(colorize(`[backend]  `, 'green') + data.toString())
  })

  const frontend = spawn('npm', ['run', 'dev'], {
    cwd: resolve(ROOT, 'frontend'),
    env: {
      ...process.env,
      VITE_BACKEND_PORT: String(backendPort),
      VITE_FRONTEND_PORT: String(frontendPort),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  children.push(frontend)

  frontend.stdout.on('data', (data) => {
    process.stdout.write(colorize(`[frontend] `, 'cyan') + data.toString())
  })
  frontend.stderr.on('data', (data) => {
    process.stderr.write(colorize(`[frontend] `, 'cyan') + data.toString())
  })

  function cleanup() {
    for (const child of children) {
      if (!child.killed) {
        child.kill('SIGTERM')
      }
    }
  }

  process.on('SIGINT', cleanup)
  process.on('SIGTERM', cleanup)

  // If either process exits, kill the other
  for (const child of children) {
    child.on('exit', (code) => {
      cleanup()
      if (code !== 0 && code !== null) {
        process.exit(code)
      }
    })
  }
}

main().catch((err) => {
  console.error(err.message)
  process.exit(1)
})
