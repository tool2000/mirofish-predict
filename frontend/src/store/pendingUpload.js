/**
 * 업로드 예정 파일과 시뮬레이션 요구사항을 임시 저장합니다.
 * 홈에서 엔진 시작 직후 화면 전환을 위해 사용하며,
 * 실제 API 호출은 Process 페이지에서 수행합니다.
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  simulationRequirement: '',
  isPending: false,
  // 기존 프로젝트 재사용
  existingProjectId: null
})

export function setPendingUpload(files, requirement) {
  state.files = files
  state.simulationRequirement = requirement
  state.isPending = true
}

export function setExistingProject(projectId, requirement) {
  state.existingProjectId = projectId
  state.simulationRequirement = requirement
  state.isPending = true
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    isPending: state.isPending,
    existingProjectId: state.existingProjectId
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.isPending = false
  state.existingProjectId = null
}

export default state
