import assert from 'node:assert/strict'
import {
  deploymentModeText,
  orderStatusLabel,
  orderStatusType,
  routingStatusLabel,
} from '../src/constants/orderDisplay.js'

const routeOnlyCompleted = {
  status: 'pending',
  routing_status: 'completed',
  materialized_instance_id: null,
  runtime_config: {
    platform_deployment: { mode: 'route_only' },
    routing_result: { route_only: true },
  },
}

assert.equal(orderStatusLabel(routeOnlyCompleted), '路由已建立')
assert.equal(orderStatusType(routeOnlyCompleted), 'success')
assert.equal(routingStatusLabel('completed', routeOnlyCompleted), '路由已建立')
assert.equal(deploymentModeText(routeOnlyCompleted), '不创建平台受控容器')

const routeOnlyPreparing = {
  ...routeOnlyCompleted,
  routing_status: 'network_binding_ready',
}

assert.equal(orderStatusLabel(routeOnlyPreparing), '网络准备中')
assert.equal(orderStatusType(routeOnlyPreparing), 'primary')
assert.equal(routingStatusLabel('network_binding_ready', routeOnlyPreparing), '网络准备中')

const normalMaterialized = {
  status: 'materialized',
  routing_status: 'completed',
  materialized_instance_id: 'instance-1',
  runtime_config: {
    platform_deployment: { mode: 'user_access_demo' },
  },
}

assert.equal(orderStatusLabel(normalMaterialized), '已生成实例/待启动')
assert.equal(orderStatusType(normalMaterialized), 'warning')
assert.equal(deploymentModeText(normalMaterialized), '用户端外部接入')

console.log('orderDisplay: ok')
