import aiohttp
from typing import Any, Dict, Mapping, Optional, Union
from marshmallow import Schema, fields, post_load

from yarl import URL

from .base import JSON, BaseModel, BaseSchema

from .error import (
    AuthenticationError, 
    ValueError, 
    NotFoundError
)

HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Content-Type": "application/json; charset=utf-8",
    "Connection": "keep-alive"
}

"""Default timeout in seconds"""
TIMEOUT: int = 10

class SessionManager(BaseModel):

    def __init__(
        self,
        headers: Optional[Mapping] = None,
        **kwargs: Any
    ) -> None:
        
        merged_headers = dict(**HEADERS)
        merged_headers.update(headers or {})

        self.session = aiohttp.ClientSession(
            headers = merged_headers
        )
        self.timeout = kwargs.pop("timeout", TIMEOUT)
        super().__init__(**kwargs)

    async def get(
        self,
        url: Union[str, URL],
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Mapping] = None,
        raise_errors: bool = True,
        return_response: bool = False,
        schema: Optional[Schema] = None,
        many: bool = False
    ) -> Any:
        """Run a wrapped session HTTP GET request.
        Note:
            This method automatically prompts the user to log in if not already logged
            in.
        Args:
            url: The url to get from.
            params: query string parameters
            headers: A dict adding to and overriding the session headers.
            raise_errors: Whether or not raise errors on GET request result.
            return_response: Whether or not return a `requests.Response` object or the
                JSON response from the request.
            schema: An instance of a `marshmallow.Schema` that represents the object
                to build.
            many: Whether to treat the output as a list of the passed schema.
        Returns:
            A JSON dictionary or a constructed object if a schema is passed. If \
                `return_response` is set then a tuple of (response, data) is passed.
        Raises:
            ValueError: If the schema is not an instance of `Schema` and is instead
                a class.
        """
        # Guard against common gotcha, passing schema class instead of instance.
        if isinstance(schema, type):
            raise ValueError("Passed Schema should be an instance not a class.")

        params = {} if params is None else params
        headers = {} if headers is None else headers

        async def do_get(url, params, headers, timeout):
            res = await self.session.get(
                url,
                params=params,
                timeout=timeout,
                headers=headers,
            )

            if res.status == 401:
                raise AuthenticationError("Unauthorized")
            
            if res.status == 403:
                raise AuthenticationError("Forbidden")

            if res.status == 404:
                raise NotFoundError("Not found")            
    
            if raise_errors:
                res.raise_for_status()

            data = await res.json() if schema is None else schema.load(await res.json(), many=many)

            return (data, res) if return_response else data

        return await do_get(str(url), params, headers, self.timeout)

    async def post(
        self,
        url: Union[str, URL],
        data: Optional[JSON] = None,
        headers: Optional[Mapping] = None,
        raise_errors: bool = True,
        return_response: bool = False,
        schema: Optional[Schema] = None,
        many: bool = False,
        error_schema: Optional[Schema] = None
    ) -> Any:
        """Run a wrapped session HTTP POST request.
        Note:
            This method automatically prompts the user to log in if not already logged
            in.
        Args:
            url: The url to post to.
            data: The payload to POST to the endpoint.
            headers: A dict adding to and overriding the session headers.
            return_response: Whether or not return a `requests.Response` object or the
                JSON response from the request.
            raise_errors: Whether or not raise errors on POST request.
            schema: An instance of a `marshmallow.Schema` that represents the object
                to build.
            many: Whether to treat the output as a list of the passed schema.
            error_schema: Represents an error response to build in the case of an error
                status code
        Returns:
            A JSON dictionary or a constructed object if a schema is passed. If \
                `return_response` is set then a tuple of (response, data) is passed.
        Raises:
            ValueError: If the schema is not an instance of `Schema` and is instead
                a class.
        """
        # Guard against common gotcha, passing schema class instead of instance.
        if isinstance(schema, type):
            raise ValueError("Passed Schema should be an instance not a class.")
        
        async def do_post(url, data, headers, timeout):
            res: aiohttp.ClientResponse = await self.session.post(
                url,
                json=data,
                timeout=timeout,
                headers=headers,
            )

            async with res:
                if res.status == 401:
                    raise AuthenticationError("Unauthorized")
                if res.status == 403:
                    raise AuthenticationError("Forbidden")                
                if res.status == 404:
                    raise NotFoundError("Not found")
                if res.status in (400, 422):
                    if error_schema is not None:
                        data = await res.json() if error_schema is None else error_schema.load(await res.json(), many=many)
                else:
                    if raise_errors:
                        res.raise_for_status()
                    data = await res.json() if schema is None else schema.load(await res.json(), many=many)

                return (data, res) if return_response else data

        return await do_post(str(url), data, headers, self.timeout)

    async def put(
        self,
        url: Union[str, URL],
        data: Optional[JSON] = None,
        headers: Optional[Mapping] = None,
        raise_errors: bool = True,
        return_response: bool = False,
        schema: Optional[Schema] = None,
        many: bool = False,
        error_schema: Optional[Schema] = None
    ) -> Any:
        """Run a wrapped session HTTP PUT request."""
        # Guard against common gotcha, passing schema class instead of instance.
        if isinstance(schema, type):
            raise ValueError("Passed Schema should be an instance not a class.")
        
        async def do_put(url, data, headers, timeout):
            res: aiohttp.ClientResponse = await self.session.put(
                url,
                json=data,
                timeout=timeout,
                headers=headers,
            )

            async with res:
                if res.status == 401:
                    raise AuthenticationError("Unauthorized")
                if res.status == 403:
                    raise AuthenticationError("Forbidden")                
                if res.status == 404:
                    raise NotFoundError("Not found")
                if res.status in (400, 422):
                    if error_schema is not None:
                        data = await res.json() if error_schema is None else error_schema.load(await res.json(), many=many)
                else:
                    if raise_errors:
                        res.raise_for_status()
                    data = await res.json() if schema is None else schema.load(await res.json(), many=many)

                return (data, res) if return_response else data

        return await do_put(str(url), data, headers, self.timeout)

    async def delete(
        self,
        url: Union[str, URL],
        data: Optional[JSON] = None,
        headers: Optional[Mapping] = None,
        raise_errors: bool = True,
        return_response: bool = False,
        schema: Optional[Schema] = None,
        many: bool = False,
        error_schema: Optional[Schema] = None
    ) -> Any:
        """Run a wrapped session HTTP DELETE request.
        Note: None
        Args:
            url: The url to post to.
            data: The payload to POST to the endpoint.
            headers: A dict adding to and overriding the session headers.
            return_response: Whether or not return a `requests.Response` object or the
                JSON response from the request.
            raise_errors: Whether or not raise errors on POST request.
            schema: An instance of a `marshmallow.Schema` that represents the object
                to build.
            many: Whether to treat the output as a list of the passed schema.
            error_schema: Represents an error response to build in the case of an error
                status code
        Returns:
            A JSON dictionary or a constructed object if a schema is passed. If \
                `return_response` is set then a tuple of (response, data) is passed.
        Raises:
            ValueError: If the schema is not an instance of `Schema` and is instead
                a class.
        """
        # Guard against common gotcha, passing schema class instead of instance.
        if isinstance(schema, type):
            raise ValueError("Passed Schema should be an instance not a class.")

        headers = {} if headers is None else headers

        async def do_delete(url, data, headers, timeout):
            res: aiohttp.ClientResponse = await self.session.delete(
                url,
                json=data,
                timeout=timeout,
                headers=headers,
            )

            async with res:
                if res.status == 401:
                    raise AuthenticationError("Unauthorized")
                if res.status == 403:
                    raise AuthenticationError("Forbidden")                
                if res.status == 404:
                    raise NotFoundError("Not found")
                if res.status in (400, 422):
                    if error_schema is not None:
                        data = await res.json() if error_schema is None else error_schema.load(await res.json(), many=many)
                else:
                    if raise_errors:
                        res.raise_for_status()
                    data = await res.json() if schema is None else schema.load(await res.json(), many=many)

                return (data, res) if return_response else data

        return await do_delete(str(url), data, headers, self.timeout)
     
    def __repr__(self) -> str:
        """Return the object as a string.
        Returns:
            The string representation of the object.
        """
        return f"SessionManager<{self}>"

    async def close(self) -> None:
        """Close the underlying session
        """
        if self.session:
            await self.session.close()

    async def __aenter__(self):
        """Enter context
        """
        pass

    async def __aexit__(self, exc_type, exc, tb):
        """Exit context
        """
        await self.close()

class SessionManagerSchema(BaseSchema):
    """Schema class for the SessionManager model."""

    __model__ = SessionManager

    headers = fields.Dict()
    proxies = fields.Dict()
    timeout = fields.Int()

    @post_load
    def make_object(self, data: JSON, **kwargs: Any) -> SessionManager:
        """Override default method to configure SessionManager object on load.
        Args:
            data: The JSON dictionary to process
            **kwargs: Not used but matches signature of `BaseSchema.make_object`
        Returns:
            A configured instance of SessionManager.
        """
        session_manager = self.__model__(**data)
        return session_manager