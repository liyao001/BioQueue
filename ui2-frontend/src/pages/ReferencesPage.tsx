import { useEffect, useMemo, useState } from 'react'
import { Box, Button, Divider, Flex, FormControl, FormLabel, Heading, IconButton, Input, SimpleGrid, Table, Tbody, Td, Th, Thead, Tooltip, Tr, Textarea, useToast, Modal, ModalOverlay, ModalContent, ModalHeader, ModalCloseButton, ModalBody, ModalFooter } from '@chakra-ui/react'
import { apiGet, apiPost, apiPatch, apiDelete } from '../lib/api'
import Pager from '../components/Pager'

export default function ReferencesPage() {
  useEffect(() => { document.title = 'References – BioQueue' }, [])
  const toast = useToast()
  const [loading, setLoading] = useState(false)
  const [refs, setRefs] = useState<Array<{ id: number; name: string; path: string; description?: string }>>([])
  const [q, setQ] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newPath, setNewPath] = useState('')
  const [newDesc, setNewDesc] = useState('')

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editPath, setEditPath] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [saving, setSaving] = useState(false)
  const [openModal, setOpenModal] = useState(false)

  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [totalCount, setTotalCount] = useState(0)
  const totalPages = Math.max(1, Math.ceil((totalCount || 0) / (pageSize || 1)))

  const filtered = useMemo(() => {
    return refs
  }, [refs])

  async function load(p = page, ps = pageSize) {
    setLoading(true)
    try {
      const qp = new URLSearchParams()
      qp.set('page_size', String(ps))
      qp.set('page', String(p))
      if ((q || '').trim()) qp.set('q', q.trim())
      const res = await apiGet(`/references/?${qp.toString()}`)
      const data = await res.json()
      if (Array.isArray(data)) {
        setRefs(data)
        setTotalCount(data.length)
      } else {
        setRefs(data.results || [])
        setTotalCount(parseInt(data.count || 0))
      }
    } catch {
      setRefs([])
      setTotalCount(0)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load(1, pageSize); setPage(1) }, [q])
  useEffect(() => { load(page, pageSize) }, [page, pageSize])

  async function onCreate() {
    const nm = newName.trim(); const p = newPath.trim()
    if (!nm || !p) { toast({ title: 'name and path are required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    setCreating(true)
    try {
      const payload: any = { name: nm, path: p }
      if (newDesc.trim()) payload.description = newDesc.trim()
      const res = await apiPost('/references/', JSON.stringify(payload))
      if (res.ok) {
        setNewName(''); setNewPath(''); setNewDesc('')
        load(1, pageSize); setPage(1)
      } else {
        const msg = await (async (r: Response) => { try { const d = await r.json(); return d?.detail || JSON.stringify(d) } catch { return `${r.status}` } })(res)
        toast({ title: msg, status: 'error', duration: 4000, isClosable: true, position: 'bottom-right' })
      }
    } finally {
      setCreating(false)
    }
  }
  function onOpenEdit(r: { id: number; name: string; path: string; description?: string }) {
    setEditingId(r.id)
    setEditName(r.name)
    setEditPath(r.path)
    setEditDesc(r.description || '')
    setOpenModal(true)
  }
  function onCloseEdit() {
    setOpenModal(false)
    setEditingId(null)
    setEditName(''); setEditPath(''); setEditDesc('')
  }
  async function onSave() {
    if (editingId == null) return
    const nm = editName.trim(); const p = editPath.trim()
    if (!nm || !p) { toast({ title: 'name and path are required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    setSaving(true)
    try {
      const res = await apiPatch(`/references/${editingId}/`, JSON.stringify({ name: nm, path: p, description: editDesc }))
      if (!res.ok) throw new Error(`${res.status}`)
      onCloseEdit(); load(page, pageSize)
    } catch (e: any) {
      toast({ title: e?.message || 'update failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    } finally {
      setSaving(false)
    }
  }
  async function onDelete(id?: number) {
    const targetId = id ?? editingId
    if (targetId == null) return
    if (!confirm('Delete this reference?')) return
    try {
      const res = await apiDelete(`/references/${targetId}/`)
      if (!res.ok) throw new Error(`${res.status}`)
      onCloseEdit(); load(page, pageSize)
    } catch (e: any) {
      toast({ title: e?.message || 'delete failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    }
  }

  return (
    <Box mx="auto" px={{ base: 2, md: 4 }}>
      <Flex align="center" justify="space-between" mb={4}>
        <Box>
          <Heading size="lg">References</Heading>
          <Box fontSize="sm" opacity={0.7}>manage custom reference files</Box>
        </Box>
      </Flex>

      <Box borderWidth="1px" borderColor="gray.200" rounded="md" boxShadow="sm" bg="white" p={{ base: 3, md: 4 }} w="100%">
        <SimpleGrid columns={1} spacing={6}>
          <Box>
            <Flex align="center" gap={2} mb={2}>
              <Input placeholder="search by name/path/id" value={q} onChange={(e)=>setQ(e.target.value)} />
              <Button onClick={()=>load(1, pageSize)} isLoading={loading}>Refresh</Button>
            </Flex>
            <Table size="sm" variant="simple">
              <Thead><Tr><Th width="80px">id</Th><Th width="240px">name</Th><Th>path</Th><Th width="300px">description</Th><Th width="120px">actions</Th></Tr></Thead>
              <Tbody>
                {filtered.map(r => (
                  <Tr key={r.id} _hover={{ bg: 'gray.50', cursor: 'pointer' }} onClick={()=>onOpenEdit(r)}>
                    <Td>{r.id}</Td>
                    <Td>{r.name}</Td>
                    <Td><Box title={r.path} noOfLines={1}>{r.path}</Box></Td>
                    <Td><Box noOfLines={2}>{r.description || ''}</Box></Td>
                    <Td>
                      <Tooltip label="Delete">
                        <IconButton aria-label="delete" size="xs" colorScheme="red" onClick={(e)=>{ e.stopPropagation(); onDelete(r.id) }} icon={<i className="fa-regular fa-trash-can"></i>} />
                      </Tooltip>
                    </Td>
                  </Tr>
                ))}
                {filtered.length === 0 && (
                  <Tr><Td colSpan={5}><Box fontSize="sm" opacity={0.7}>no references</Box></Td></Tr>
                )}
              </Tbody>
            </Table>
            <Pager page={page} totalPages={totalPages} loading={loading} onChange={(v)=>setPage(v)} />
          </Box>

          <Box>
            <Divider my={4} />
            <Heading as="h4" size="sm" mb={2}>Add reference</Heading>
            <FormControl mb={2}>
              <FormLabel>Name</FormLabel>
              <Input value={newName} onChange={(e)=>setNewName(e.target.value)} placeholder="reference name" />
            </FormControl>
            <FormControl mb={2}>
              <FormLabel>Path</FormLabel>
              <Input value={newPath} onChange={(e)=>setNewPath(e.target.value)} placeholder="/path/to/ref" />
            </FormControl>
            <FormControl mb={3}>
              <FormLabel>Description</FormLabel>
              <Textarea value={newDesc} onChange={(e)=>setNewDesc(e.target.value)} rows={3} placeholder="optional" />
            </FormControl>
            <Button onClick={onCreate} isLoading={creating} colorScheme="blue">Create</Button>
          </Box>
        </SimpleGrid>
      </Box>

      <Modal isOpen={openModal} onClose={onCloseEdit} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Edit reference {editingId != null ? `#${editingId}` : ''}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <FormControl mb={3}>
              <FormLabel>Name</FormLabel>
              <Input value={editName} onChange={(e)=>setEditName(e.target.value)} />
            </FormControl>
            <FormControl mb={3}>
              <FormLabel>Path</FormLabel>
              <Input value={editPath} onChange={(e)=>setEditPath(e.target.value)} />
            </FormControl>
            <FormControl mb={1}>
              <FormLabel>Description</FormLabel>
              <Textarea value={editDesc} onChange={(e)=>setEditDesc(e.target.value)} rows={4} />
            </FormControl>
          </ModalBody>
          <ModalFooter>
            <Button variant="outline" mr={3} onClick={onCloseEdit}>Cancel</Button>
            <Button colorScheme="red" mr={3} onClick={()=>onDelete()}><i className="fa-regular fa-trash-can"></i>&nbsp;Delete</Button>
            <Button colorScheme="blue" isLoading={saving} onClick={onSave}>Save</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  )
}
