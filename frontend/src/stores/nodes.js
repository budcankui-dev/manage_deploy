import { defineStore } from 'pinia'
import { ref } from 'vue'
import { nodesApi } from '@/api'

export const useNodesStore = defineStore('nodes', () => {
  const nodes = ref([])
  const loading = ref(false)

  async function fetchNodes(params = {}) {
    loading.value = true
    try {
      const { data } = await nodesApi.list(params)
      nodes.value = data
    } finally {
      loading.value = false
    }
  }

  async function createNode(nodeData) {
    const { data } = await nodesApi.create(nodeData)
    nodes.value.push(data)
    return data
  }

  async function updateNode(id, nodeData) {
    const { data } = await nodesApi.update(id, nodeData)
    const index = nodes.value.findIndex(n => n.id === id)
    if (index !== -1) {
      nodes.value[index] = data
    }
    return data
  }

  async function deleteNode(id) {
    await nodesApi.delete(id)
    nodes.value = nodes.value.filter(n => n.id !== id)
  }

  async function syncNodeResources(id) {
    const { data } = await nodesApi.syncResources(id)
    const index = nodes.value.findIndex(n => n.id === id)
    if (index !== -1) {
      nodes.value[index] = data
    }
    return data
  }

  return {
    nodes,
    loading,
    fetchNodes,
    createNode,
    updateNode,
    deleteNode,
    syncNodeResources
  }
})
