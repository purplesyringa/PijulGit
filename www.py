import aiohttp

session = None

async def init():
    global session
    session = aiohttp.ClientSession()

async def destroy():
    await session.close()

async def get(url):
    async with session.get(url) as response:
        return await response.text()

async def post(url, data=None):
    async with session.post(url, data=data) as response:
        return await response.text()

async def delete(url):
    async with session.delete(url) as response:
        return await response.text()