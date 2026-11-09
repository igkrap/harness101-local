const assert=require('node:assert/strict');
// Register the native handler before clicking; window.confirm pauses the page.
async function confirmDelete(page,button,accept) {
 const native=[],pending=[],errors=[];let custom=false;
 const handler=dialog=>{
  native.push({type:dialog.type(),message:dialog.message()});
  pending.push(Promise.resolve().then(()=>accept?dialog.accept():dialog.dismiss()).catch(e=>errors.push(String(e))));
 };
 page.on('dialog',handler);
 try {
  await button.click();
  const visibleDialog=page.locator('[role="dialog"]:visible, [role="alertdialog"]:visible');
  for(let i=0;i<100&&!native.length&&!await visibleDialog.count();i++)await page.waitForTimeout(50);
  if(native.length){await Promise.all(pending);assert.ok(native.every(d=>d.type==='confirm'),'Deletion must use a cancellable confirmation');assert.deepEqual(errors,[]);}
  else {
   const dialog=visibleDialog;assert.equal(await dialog.count(),1,'Require visible deletion confirmation before data changes');
   const name=accept?/^(삭제(?:하기)?|확인|예|Delete|Confirm|Yes)$/i:/^(취소|아니오|Cancel|No)$/i;
   const action=dialog.getByRole('button',{name});assert.equal(await action.count(),1,'Dialog must offer a clear confirm/cancel action');await action.click();await dialog.waitFor({state:'hidden'});custom=true;
  }
  return {accepted:accept,mode:custom?'custom':'native',native};
 }finally{page.off('dialog',handler);await Promise.all(pending);}
}
module.exports={confirmDelete};
