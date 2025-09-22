import { useEffect, useMemo, useState } from 'react'
import { Box, Button, Divider, Flex, FormControl, FormLabel, Heading, IconButton, Input, Select, SimpleGrid, Table, Tbody, Td, Th, Thead, Tooltip, Tr, useToast, Modal, ModalOverlay, ModalContent, ModalHeader, ModalCloseButton, ModalBody, ModalFooter } from '@chakra-ui/react'
import { apiGet, apiPost, apiPatch, apiDelete } from '../lib/api'
import Pager from '../components/Pager'

export default function VirtualEnvsPage() {
  useEffect(() => { document.title = 'Virtual Environments – BioQueue' }, [])
  const toast = useToast()
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<Array<{ id: number; name: string; ve_type: string; value: string; activation_command?: string }>>([])
  const [q, setQ] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('conda')
  const [newValue, setNewValue] = useState('')
  const [newAct, setNewAct] = useState('')

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editType, setEditType] = useState('conda')
  const [editValue, setEditValue] = useState('')
  const [editAct, setEditAct] = useState('')
  const [saving, setSaving] = useState(false)
  const [openModal, setOpenModal] = useState(false)

  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [totalCount, setTotalCount] = useState(0)
  const totalPages = Math.max(1, Math.ceil((totalCount || 0) / (pageSize || 1)))

  const filtered = useMemo(() => {
    // server filters
    return items
  }, [items])

  async function load(p = page, ps = pageSize) {
    setLoading(true)
    try {
      const qp = new URLSearchParams()
      qp.set('page_size', String(ps))
      qp.set('page', String(p))
      if ((q || '').trim()) qp.set('q', q.trim())
      const res = await apiGet(`/virtual-environments/?${qp.toString()}`)
      const data = await res.json()
      if (Array.isArray(data)) {
        setItems(data)
        setTotalCount(data.length)
      } else {
        setItems(data.results || [])
        setTotalCount(parseInt(data.count || 0))
      }
    } catch {
      setItems([])
      setTotalCount(0)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load(1, pageSize); setPage(1) }, [q])
  useEffect(() => { load(page, pageSize) }, [page, pageSize])

  async function onCreate() {
    const nm = newName.trim(); const v = newValue.trim()
    if (!nm || !v) { toast({ title: 'name and value are required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    setCreating(true)
    try {
      const payload: any = { name: nm, ve_type: newType, value: v }
      if (newAct.trim()) payload.activation_command = newAct.trim()
      const res = await apiPost('/virtual-environments/', JSON.stringify(payload))
      if (res.ok) {
        setNewName(''); setNewType('conda'); setNewValue(''); setNewAct('')
        load(1, pageSize); setPage(1)
      } else {
        const msg = await (async (r: Response) => { try { const d = await r.json(); return d?.detail || JSON.stringify(d) } catch { return `${r.status}` } })(res)
        toast({ title: msg, status: 'error', duration: 4000, isClosable: true, position: 'bottom-right' })
      }
    } finally {
      setCreating(false)
    }
  }
  function onOpenEdit(r: { id: number; name: string; ve_type: string; value: string; activation_command?: string }) {
    setEditingId(r.id)
    setEditName(r.name)
    setEditType(r.ve_type)
    setEditValue(r.value)
    setEditAct(r.activation_command || '')
    setOpenModal(true)
  }
  function onCloseEdit() {
    setOpenModal(false)
    setEditingId(null)
    setEditName(''); setEditType('conda'); setEditValue(''); setEditAct('')
  }
  async function onSave() {
    if (editingId == null) return
    const nm = editName.trim(); const v = editValue.trim()
    if (!nm || !v) { toast({ title: 'name and value are required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    setSaving(true)
    try {
      const res = await apiPatch(`/virtual-environments/${editingId}/`, JSON.stringify({ name: nm, ve_type: editType, value: v, activation_command: editAct }))
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
    if (!confirm('Delete this environment?')) return
    try {
      const res = await apiDelete(`/virtual-environments/${targetId}/`)
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
          <Heading size="lg">Virtual Environments</Heading>
          <Box fontSize="sm" opacity={0.7}>manage conda/venv environments</Box>
        </Box>
      </Flex>

      <Box borderWidth="1px" borderColor="gray.200" rounded="md" boxShadow="sm" bg="white" p={{ base: 3, md: 4 }} w="100%">
        <SimpleGrid columns={1} spacing={6}>
          <Box>
            <Flex align="center" gap={2} mb={2}>
              <Input placeholder="search by name/type/id" value={q} onChange={(e)=>setQ(e.target.value)} />
              <Button onClick={()=>load(1, pageSize)} isLoading={loading}>Refresh</Button>
            </Flex>
            <Table size="sm" variant="simple">
              <Thead><Tr><Th width="80px">id</Th><Th width="240px">name</Th><Th width="160px">type</Th><Th>value</Th><Th width="240px">activation</Th><Th width="120px">actions</Th></Tr></Thead>
              <Tbody>
                {filtered.map(r => (
                  <Tr key={r.id} _hover={{ bg: 'gray.50', cursor: 'pointer' }} onClick={()=>onOpenEdit(r)}>
                    <Td>{r.id}</Td>
                    <Td>{r.name}</Td>
                    <Td>{r.ve_type}</Td>
                    <Td><Box title={r.value} noOfLines={1}>{r.value}</Box></Td>
                    <Td><Box noOfLines={1}>{r.activation_command || ''}</Box></Td>
                    <Td>
                      <Tooltip label="Delete">
                        <IconButton aria-label="delete" size="xs" colorScheme="red" onClick={(e)=>{ e.stopPropagation(); onDelete(r.id) }} icon={<i className="fa-regular fa-trash-can"></i>} />
                      </Tooltip>
                    </Td>
                  </Tr>
                ))}
                {filtered.length === 0 && (
                  <Tr><Td colSpan={6}><Box fontSize="sm" opacity={0.7}>no environments</Box></Td></Tr>
                )}
              </Tbody>
            </Table>
            <Pager page={page} totalPages={totalPages} loading={loading} onChange={(v)=>setPage(v)} />
          </Box>

          <Box>
            <Divider my={4} />
            <Heading as="h4" size="sm" mb={2}>Add environment</Heading>
            <FormControl mb={2}>
              <FormLabel>Name</FormLabel>
              <Input value={newName} onChange={(e)=>setNewName(e.target.value)} placeholder="env name" />
            </FormControl>
            <FormControl mb={2}>
              <FormLabel>Type</FormLabel>
              <Select value={newType} onChange={(e)=>setNewType(e.target.value)}>
                <option value="conda">conda</option>
                <option value="venv">venv</option>
              </Select>
            </FormControl>
            <FormControl mb={2}>
              <FormLabel>Value</FormLabel>
              <Input value={newValue} onChange={(e)=>setNewValue(e.target.value)} placeholder="env path or name" />
            </FormControl>
            <FormControl mb={3}>
              <FormLabel>Activation command (optional)</FormLabel>
              <Input value={newAct} onChange={(e)=>setNewAct(e.target.value)} placeholder="source activate ..." />
            </FormControl>
            <Button onClick={onCreate} isLoading={creating} colorScheme="blue">Create</Button>
          </Box>
        </SimpleGrid>
      </Box>

      <Modal isOpen={openModal} onClose={onCloseEdit} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Edit environment {editingId != null ? `#${editingId}` : ''}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <FormControl mb={3}>
              <FormLabel>Name</FormLabel>
              <Input value={editName} onChange={(e)=>setEditName(e.target.value)} />
            </FormControl>
            <FormControl mb={3}>
              <FormLabel>Type</FormLabel>
              <Select value={editType} onChange={(e)=>setEditType(e.target.value)}>
                <option value="conda">conda</option>
                <option value="venv">venv</option>
              </Select>
            </FormControl>
            <FormControl mb={3}>
              <FormLabel>Value</FormLabel>
              <Input value={editValue} onChange={(e)=>setEditValue(e.target.value)} />
            </FormControl>
            <FormControl mb={1}>
              <FormLabel>Activation command (optional)</FormLabel>
              <Input value={editAct} onChange={(e)=>setEditAct(e.target.value)} />
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
