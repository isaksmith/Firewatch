import { TopBar } from '../components/TopBar'

/** The FireNode Explorer from sensors/viewer: the exploded 3D node design. It is its own static app at /nodes/. */
export function Design() {
  return (
    <div className="flex h-full flex-col bg-void">
      <TopBar />
      <iframe src="/nodes/?embed" title="FireNode design: exploded 3D view" className="min-h-0 w-full flex-1 border-0" />
    </div>
  )
}
