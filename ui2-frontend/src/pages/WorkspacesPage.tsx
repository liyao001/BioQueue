import { useEffect, useState } from 'react'
import { Box, Button, Divider, Flex, FormControl, FormLabel, Heading, IconButton, Input, Select, SimpleGrid, Spinner, Table, Tbody, Td, Th, Thead, Tooltip, Tr, useToast, Textarea, Text, Modal, ModalOverlay, ModalContent, ModalHeader, ModalCloseButton, ModalBody, ModalFooter } from '@chakra-ui/react'
import { useLocation } from 'react-router-dom'
import Pager from '../components/Pager'
import { apiGet, apiPost, apiPatch, apiDelete } from '../lib/api'

type Workspace = { id: number; name: string; description?: string }

export default function WorkspacesPage() {
  const location = useLocation()
  const toast = useToast()
  useEffect(() => { document.title = 'Workspaces – BioQueue' }, [])
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<Workspace[]>([])
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [totalCount, setTotalCount] = useState(0)

  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [saving, setSaving] = useState(false)
  const [openModal, setOpenModal] = useState(false)

  async function loadWorkspaces() {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (q.trim()) params.append('q', q.trim())
      const res = await apiGet(`/workspaces/?${params.toString()}`)
      if (!res.ok) {
        if ((res.status === 400 || res.status === 404) && page !== 1) { setPage(1); return }
      }
      const data = await res.json()
      if (Array.isArray(data)) {
        setItems(data)
        setTotalCount(data.length)
        if (data.length === 0 && page > 1) { setPage(1); return }
      } else {
        setItems(Array.isArray(data.results) ? data.results : [])
        const countNum = parseInt(data.count || 0)
        setTotalCount(countNum)
        const pages = Math.max(1, Math.ceil((countNum || 0) / (pageSize || 1)))
        if (page > pages && page !== 1) { setPage(1); return }
      }
    } catch {
      setItems([])
      setTotalCount(0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadWorkspaces() }, [q, page, pageSize])
  useEffect(() => {
    const sp = new URLSearchParams(location.search)
    const q0 = sp.get('q') || ''
    if (q0 && q0 !== q) setQ(q0)
  }, [location.search])

  async function onCreate() {
    const name = newName.trim()
    if (!name) { toast({ title: 'name is required', status: 'error', duration: 2500, isClosable: true, position: 'bottom-right' }); return }
    setCreating(true)
    try {
      const payload: any = { name }
      const desc = newDesc.trim()
      if (desc) payload.description = desc
      const res = await apiPost('/workspaces/', JSON.stringify(payload))
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'workspace created', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      setNewName('')
      setNewDesc('')
      setPage(1)
      loadWorkspaces()
    } catch (e: any) {
      toast({ title: e?.message || 'create failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    } finally {
      setCreating(false)
    }
  }

  function onStartEdit(ws: Workspace) {
    setEditingId(ws.id)
    setEditName(ws.name)
    setEditDesc(ws.description || '')
    setOpenModal(true)
  }
  function onCancelEdit() {
    setOpenModal(false)
    setEditingId(null)
    setEditName('')
    setEditDesc('')
  }
  async function onSaveEdit(id: number) {
    const name = editName.trim()
    if (!name) { toast({ title: 'name cannot be empty', status: 'error', duration: 2500, isClosable: true, position: 'bottom-right' }); return }
    setSaving(true)
    try {
      const res = await apiPatch(`/workspaces/${id}/`, JSON.stringify({ name, description: editDesc }))
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'workspace updated', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      onCancelEdit()
      loadWorkspaces()
    } catch (e: any) {
      toast({ title: e?.message || 'update failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    } finally {
      setSaving(false)
    }
  }
  async function onDelete(ws: Workspace) {
    if (!confirm(`Delete workspace "${ws.name}"?`)) return
    try {
      const res = await apiDelete(`/workspaces/${ws.id}/`)
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'deleted', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      loadWorkspaces()
    } catch (e: any) {
      toast({ title: e?.message || 'delete failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    }
  }

  return (
    <Box>
      <Flex align="center" justify="space-between" mb={4}>
        <Box>
          <Heading size="lg">Workspaces</Heading>
          <Box fontSize="sm" opacity={0.7}>create, rename and delete workspaces</Box>
        </Box>
      </Flex>

      <Flex gap={3} wrap="wrap" mb={3} align="center">
        <Input placeholder="search workspaces" value={q} onChange={(e)=>{ setQ(e.target.value); setPage(1) }} width="260px" />
        <Flex align="center" gap={2}>
          <Box as="label" fontSize="sm">page size</Box>
          <Select size="sm" width="auto" value={pageSize} onChange={(e)=>{ const v = parseInt(e.target.value)||20; setPageSize(v); setPage(1) }}>
            {[10,20,30,40,50].map(s => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Flex>
      </Flex>

      <Box borderWidth="1px" borderColor="gray.200" rounded="md" boxShadow="sm" bg="white" p={{ base: 3, md: 4 }} w="100%">
        <SimpleGrid columns={1} spacing={6}>
          <Box>
            {loading ? (
              <Flex align="center" justify="center" p={6}><Spinner size="sm" /> <Box ml={2} fontSize="sm" opacity={0.7}>loading…</Box></Flex>
            ) : (
              <Table size="sm" variant="simple">
                <Thead><Tr><Th width="80px">id</Th><Th width="260px">name</Th><Th>description</Th><Th width="120px">actions</Th></Tr></Thead>
                <Tbody>
                  {items.map(ws => (
                    <Tr key={ws.id} _hover={{ bg: 'gray.50', cursor: 'pointer' }} onClick={()=>onStartEdit(ws)}>
                      <Td>{ws.id}</Td>
                      <Td>{ws.name}</Td>
                      <Td><Box fontSize="sm" noOfLines={1} title={ws.description || ''}>{ws.description || ''}</Box></Td>
                      <Td>
                        <Tooltip label="Delete">
                          <IconButton aria-label="delete" size="xs" colorScheme="red" onClick={(e)=>{ e.stopPropagation(); onDelete(ws) }} icon={<i className="fa-regular fa-trash-can"></i>} />
                        </Tooltip>
                      </Td>
                    </Tr>
                  ))}
                  {items.length === 0 && (
                    <Tr><Td colSpan={4}><Box fontSize="sm" opacity={0.7}>no workspaces</Box></Td></Tr>
                  )}
                </Tbody>
              </Table>
            )}
            <Pager page={page} totalPages={Math.max(1, Math.ceil((totalCount || 0) / (pageSize || 1)))} loading={loading} onChange={(v)=>setPage(v)} />
          </Box>

          <Box>
            <Divider my={4} />
            <Heading as="h4" size="sm" mb={2}>Add workspace</Heading>
            <FormControl mb={2}>
              <FormLabel>Name</FormLabel>
              <Input value={newName} onChange={(e)=>setNewName(e.target.value)} placeholder="workspace name" />
            </FormControl>
            <FormControl mb={3}>
              <FormLabel>Description (optional)</FormLabel>
              <Textarea value={newDesc} onChange={(e)=>setNewDesc(e.target.value)} rows={3} placeholder="Enter description" />
            </FormControl>
            <Button onClick={onCreate} isLoading={creating} colorScheme="blue">Create</Button>
          </Box>
        </SimpleGrid>
      </Box>

      <Modal isOpen={openModal} onClose={onCancelEdit} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Edit workspace {editingId != null ? `#${editingId}` : ''}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <FormControl mb={3}>
              <FormLabel>Name</FormLabel>
              <Input value={editName} onChange={(e)=>setEditName(e.target.value)} />
            </FormControl>
            <FormControl mb={1}>
              <FormLabel>Description</FormLabel>
              <Textarea value={editDesc} onChange={(e)=>setEditDesc(e.target.value)} rows={6} />
            </FormControl>
          </ModalBody>
          <ModalFooter>
            <Button variant="outline" mr={3} onClick={onCancelEdit}>Cancel</Button>
            <Button colorScheme="red" mr={3} onClick={()=>{ if (editingId!=null) onDelete({ id: editingId, name: editName, description: editDesc }) }}><i className="fa-regular fa-trash-can"></i>&nbsp;Delete</Button>
            <Button colorScheme="blue" isLoading={saving} onClick={()=>{ if (editingId!=null) onSaveEdit(editingId) }}>Save</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  )
}


