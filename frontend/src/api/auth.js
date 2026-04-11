import service from './index'

export const getMe = () => service.get('/api/auth/me')
export const updateMe = (data) => service.patch('/api/auth/me', data)
export const changePassword = (data) => service.post('/api/auth/me/change-password', data)

export const listCompanies = () => service.get('/api/auth/admin/companies')
export const createCompany = (data) => service.post('/api/auth/admin/companies', data)
export const updateCompany = (id, data) => service.patch(`/api/auth/admin/companies/${id}`, data)
export const deleteCompany = (id) => service.delete(`/api/auth/admin/companies/${id}`)

export const listUsers = (companyId) => {
  const params = companyId ? { company_id: companyId } : {}
  return service.get('/api/auth/admin/users', { params })
}
export const createUser = (data) => service.post('/api/auth/admin/users', data)
export const updateUser = (id, data) => service.patch(`/api/auth/admin/users/${id}`, data)
export const resetUserPassword = (id, data) => service.post(`/api/auth/admin/users/${id}/reset-password`, data)
