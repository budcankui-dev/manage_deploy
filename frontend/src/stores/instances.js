import { defineStore } from 'pinia'
import { ref } from 'vue'
import { instancesApi } from '@/api'

export const useInstancesStore = defineStore('instances', () => {
  const instances = ref([])
  const loading = ref(false)
  const currentInstance = ref(null)

  async function fetchInstances() {
    loading.value = true
    try {
      const { data } = await instancesApi.list()
      instances.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchInstance(id) {
    loading.value = true
    try {
      const { data } = await instancesApi.get(id)
      currentInstance.value = data
      return data
    } finally {
      loading.value = false
    }
  }

  async function createInstance(instanceData) {
    const { data } = await instancesApi.create(instanceData)
    instances.value.push(data)
    return data
  }

  async function updateInstance(id, payload) {
    const { data } = await instancesApi.update(id, payload)
    const idx = instances.value.findIndex(i => i.id === id)
    if (idx !== -1) {
      instances.value[idx] = data
    }
    return data
  }

  async function deleteInstance(id) {
    await instancesApi.delete(id)
    instances.value = instances.value.filter(i => i.id !== id)
  }

  async function startInstance(id) {
    await instancesApi.start(id)
    await fetchInstances()
  }

  async function stopInstance(id) {
    await instancesApi.stop(id)
    await fetchInstances()
  }

  async function restartInstance(id) {
    await instancesApi.restart(id)
    await fetchInstances()
  }

  async function scheduleInstance(id, scheduleData) {
    await instancesApi.schedule(id, scheduleData)
    await fetchInstances()
  }

  async function batchStart(ids) {
    const { data } = await instancesApi.batchStart(ids)
    await fetchInstances()
    return data
  }

  async function batchStop(ids) {
    const { data } = await instancesApi.batchStop(ids)
    await fetchInstances()
    return data
  }

  async function batchDelete(ids) {
    const { data } = await instancesApi.batchDelete(ids)
    await fetchInstances()
    return data
  }

  return {
    instances,
    loading,
    currentInstance,
    fetchInstances,
    fetchInstance,
    createInstance,
    updateInstance,
    deleteInstance,
    startInstance,
    stopInstance,
    restartInstance,
    scheduleInstance,
    batchStart,
    batchStop,
    batchDelete
  }
})
