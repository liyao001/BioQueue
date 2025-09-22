import { useEffect, useState } from 'react'
import { Box, ButtonGroup, IconButton, Input, Text, Flex } from '@chakra-ui/react'

export default function Pager(props: {
  page: number
  totalPages: number
  loading?: boolean
  onChange: (newPage: number) => void
}) {
  const { page, totalPages, loading, onChange } = props
  const hasPrev = page > 1
  const hasNext = page < Math.max(1, totalPages || 1)
  const maxPages = Math.max(1, totalPages || 1)
  const [pageInput, setPageInput] = useState<string>(String(page))
  useEffect(() => { setPageInput(String(page)) }, [page])

  function clamp(v: number): number {
    if (!isFinite(v) || isNaN(v)) return 1
    return Math.max(1, Math.min(maxPages, v))
  }

  return (
    <Flex mt={4} justify="center">
      <ButtonGroup isAttached size="sm" variant="outline">
        <IconButton aria-label="first" isDisabled={!hasPrev || !!loading} onClick={()=>onChange(1)} icon={<span>&laquo;</span>} />
        <IconButton aria-label="previous" isDisabled={!hasPrev || !!loading} onClick={()=>onChange(Math.max(1, page-1))} icon={<span>&lsaquo;</span>} />
        <Box display="flex" alignItems="center" px={3} border="0" bg="transparent">
          <Text fontSize="sm" mr={2}>Page</Text>
          <Input
            type="number"
            size="sm"
            width="70px"
            min={1}
            max={maxPages}
            value={pageInput}
            onChange={(e)=>setPageInput(e.target.value)}
            onKeyDown={(e)=>{ if (e.key === 'Enter') { const v = clamp(parseInt(pageInput||'1')||1); if (v !== page) onChange(v) } }}
            onBlur={()=>{ const v = clamp(parseInt(pageInput||'1')||1); if (v !== page) onChange(v) }}
            border="none"
            _focus={{ boxShadow: 'none' }}
          />
          <Text fontSize="sm" ml={2}>of {maxPages}</Text>
        </Box>
        <IconButton aria-label="next" isDisabled={!hasNext || !!loading} onClick={()=>onChange(page+1)} icon={<span>&rsaquo;</span>} />
        <IconButton aria-label="last" isDisabled={!hasNext || !!loading} onClick={()=>onChange(maxPages)} icon={<span>&raquo;</span>} />
      </ButtonGroup>
    </Flex>
  )
}
