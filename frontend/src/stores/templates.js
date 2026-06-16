import { defineStore } from 'pinia'
import { ref } from 'vue'
import { templatesApi } from '@/api'

export const useTemplatesStore = defineStore('templates', () => {
  const templates = ref([])
  const loading = ref(false)
  const currentTemplate = ref(null)

  async function fetchTemplates() {
    loading.value = true
    try {
      const { data } = await templatesApi.list()
      templates.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchTemplate(id) {
    loading.value = true
    try {
      const { data } = await templatesApi.get(id)
      currentTemplate.value = data
      return data
    } finally {
      loading.value = false
    }
  }

  async function createTemplate(templateData) {
    const { data } = await templatesApi.create(templateData)
    templates.value.push(data)
    return data
  }

  async function updateTemplate(id, templateData) {
    const { data } = await templatesApi.update(id, templateData)
    const index = templates.value.findIndex(t => t.id === id)
    if (index !== -1) {
      templates.value[index] = data
    }
    return data
  }

  async function deleteTemplate(id, config = {}) {
    await templatesApi.delete(id, config)
    templates.value = templates.value.filter(t => t.id !== id)
  }

  return {
    templates,
    loading,
    currentTemplate,
    fetchTemplates,
    fetchTemplate,
    createTemplate,
    updateTemplate,
    deleteTemplate
  }
})
