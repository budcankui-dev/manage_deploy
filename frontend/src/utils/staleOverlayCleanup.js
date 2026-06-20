export function cleanupStaleElementOverlays() {
  const overlays = document.querySelectorAll('.el-overlay, .el-loading-mask')
  overlays.forEach((element) => {
    const text = element.textContent || ''
    if (element.classList.contains('el-loading-mask')) {
      const hasSpinner = element.querySelector('.el-loading-spinner')
      if (!hasSpinner && !text.includes('加载中')) {
        element.remove()
      }
      return
    }

    const hasActivePanel = element.querySelector('.el-drawer, .el-dialog, .el-message-box')
    if (!hasActivePanel && !text.includes('加载中')) {
      element.remove()
    }
  })

  if (!document.querySelector('.el-overlay .el-drawer, .el-overlay .el-dialog, .el-overlay .el-message-box')) {
    document.body.classList.remove('el-popup-parent--hidden')
  }
}
