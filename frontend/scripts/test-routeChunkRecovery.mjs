import assert from 'node:assert/strict'

import {
  buildChunkReloadStorageKey,
  isDynamicImportLoadError,
} from '../src/utils/routeChunkRecovery.js'

assert.equal(
  isDynamicImportLoadError(
    new TypeError(
      'Failed to fetch dynamically imported module: http://10.112.244.94:8182/assets/NodesView-aNnP3YQL.js'
    )
  ),
  true
)

assert.equal(
  isDynamicImportLoadError(new Error('Importing a module script failed.')),
  true
)

assert.equal(
  isDynamicImportLoadError({ message: 'Loading chunk SystemSettingsView failed.' }),
  true
)

assert.equal(isDynamicImportLoadError(new Error('普通接口请求失败')), false)
assert.equal(buildChunkReloadStorageKey('/nodes'), 'manage-deploy:chunk-reload:/nodes')

console.log('route chunk recovery tests passed')
