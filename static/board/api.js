async function apiGetStages(boardId) {
  const res = await fetch(`/api/stages?board_id=${boardId}`);
  return res.json();
}

async function apiGetTaskTypes(boardId) {
  const res = await fetch(`/api/task-types?board_id=${boardId}`);
  return res.json();
}

async function apiGetFilters(boardId) {
  const res = await fetch(`/api/filters?board_id=${boardId}`);
  return res.json();
}

async function apiGetBoardMembers(boardId) {
  return fetch(`/api/boards/${boardId}/members`);
}

async function apiReorderTasks(payload) {
  return fetch('/api/tasks/reorder', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiReorderStages(payload) {
  return fetch('/api/stages/reorder', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiCreateStage(payload) {
  return fetch('/api/stages', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiUpdateStage(stageId, payload) {
  return fetch(`/api/stages/${stageId}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiDeleteStage(stageId) {
  return fetch(`/api/stages/${stageId}`, {method: 'DELETE'});
}

async function apiCreateTask(payload) {
  return fetch('/api/tasks', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiGetTask(taskId) {
  return fetch(`/api/tasks/${taskId}`);
}

async function apiUpdateTask(taskId, payload) {
  return fetch(`/api/tasks/${taskId}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiMoveTask(taskId, payload) {
  return fetch(`/api/tasks/${taskId}/move`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiDeleteTask(taskId) {
  return fetch(`/api/tasks/${taskId}`, {method: 'DELETE'});
}

async function apiCreateChecklistItem(taskId, payload) {
  return fetch(`/api/tasks/${taskId}/checklist`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiUpdateChecklistItem(taskId, itemId, payload) {
  return fetch(`/api/tasks/${taskId}/checklist/${itemId}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiDeleteChecklistItem(taskId, itemId) {
  return fetch(`/api/tasks/${taskId}/checklist/${itemId}`, {method: 'DELETE'});
}

async function apiClearCompletedStage(stageId) {
  return fetch(`/api/stages/${stageId}/clear-completed`, {method: 'POST'});
}

async function apiUpdateStageConfig(stageId, payload) {
  return fetch(`/api/stages/${stageId}/config`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiUpdateBoard(boardId, payload) {
  return fetch(`/api/boards/${boardId}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiAddBoardMember(boardId, payload) {
  return fetch(`/api/boards/${boardId}/members`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiUpdateBoardMember(boardId, userId, payload) {
  return fetch(`/api/boards/${boardId}/members/${userId}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiDeleteBoardMember(boardId, userId) {
  return fetch(`/api/boards/${boardId}/members/${userId}`, {method: 'DELETE'});
}

async function apiUpsertTaskRecurrence(taskId, payload) {
  return fetch(`/api/tasks/${taskId}/recurrence`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

async function apiDeleteTaskRecurrence(taskId) {
  return fetch(`/api/tasks/${taskId}/recurrence`, {method: 'DELETE'});
}
