const CHUNK_RELOAD_PREFIX = 'manage-deploy:chunk-reload:'

const DYNAMIC_IMPORT_ERROR_PATTERNS = [
  /failed to fetch dynamically imported module/i,
  /importing a module script failed/i,
  /error loading dynamically imported module/i,
  /loading chunk .+ failed/i,
]

export function isDynamicImportLoadError(error) {
  const message = String(error?.message || error || '')
  return DYNAMIC_IMPORT_ERROR_PATTERNS.some((pattern) => pattern.test(message))
}

export function buildChunkReloadStorageKey(fullPath = '') {
  return `${CHUNK_RELOAD_PREFIX}${fullPath || '/'}`
}

export function clearChunkReloadMarker(fullPath = '') {
  try {
    window.sessionStorage.removeItem(buildChunkReloadStorageKey(fullPath))
  } catch {
    // sessionStorage can be unavailable in restricted browser contexts.
  }
}

export function recoverFromChunkLoadError(to, notify) {
  const targetPath = to?.fullPath || window.location.pathname || '/'
  const retryKey = buildChunkReloadStorageKey(targetPath)

  try {
    if (window.sessionStorage.getItem(retryKey) === '1') {
      return false
    }
    window.sessionStorage.setItem(retryKey, '1')
  } catch {
    // If storage is blocked, still try one browser-level reload.
  }

  notify?.('页面资源已更新，正在刷新后重试')
  window.location.assign(targetPath)
  return true
}
